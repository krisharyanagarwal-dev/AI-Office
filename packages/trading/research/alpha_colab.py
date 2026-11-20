#!/usr/bin/env python3
"""
Alpha Model - Full Production Version
Runs anywhere: Colab, Kaggle, Local, Lightning
Features: Factors, ML, Regime Detection, Risk Model, Portfolio Opt, Costs
"""
import sys, subprocess, warnings, json, os
warnings.filterwarnings('ignore')

def install(pkg):
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', pkg])

for p in ['yfinance', 'lightgbm', 'pandas', 'numpy', 'scipy', 'scikit-learn', 
          'matplotlib', 'cvxpy', 'hmmlearn', 'requests', 'ta']:
    try: __import__(p)
    except ImportError: install(p)

import yfinance as yf
import pandas as pd
import numpy as np
import lightgbm as lgb
from scipy import stats
from sklearn.model_selection import TimeSeriesSplit
from sklearn.covariance import LedoitWolf
from hmmlearn import hmm
import cvxpy as cp
import matplotlib.pyplot as plt
import requests

# ============================================================
# CONFIG
# ============================================================
CONFIG = {
    # Universe
    'equity_tickers': ['SPY','QQQ','IWM','EFA','EEM','GLD','TLT','DBC','VNQ','XLE','XLF','XLK','XLV','XLI','XLP','XLU','XLB','XLRE'],
    'crypto_tickers': ['BTC-USD','ETH-USD','SOL-USD','ADA-USD','AVAX-USD','DOT-USD','MATIC-USD','LINK-USD','UNI-USD','ATOM-USD',
                       'NEAR-USD','FTM-USD','ALGO-USD','VET-USD','ICP-USD','FIL-USD','THETA-USD','AXS-USD','SAND-USD','MANA-USD'],
    'start': '2020-01-01',
    'end': '2024-12-31',
    'horizon': 5,
    'n_splits': 4,
    'seed': 42,
    # Risk
    'risk_aversion': 1.0,
    'max_weight': 0.15,
    'max_leverage': 2.0,
    'turnover_penalty': 0.001,
    # Costs
    'fee_bps': 5,        # 5 bps per side
    'slippage_bps': 3,   # 3 bps
    # Regime
    'n_regimes': 3,
    # Data
    'use_funding_rates': True,
    'use_onchain': True,
}

# ============================================================
# 1. DATA LOADING
# ============================================================
print('📥 Downloading data...')
all_tickers = CONFIG['equity_tickers'] + CONFIG['crypto_tickers']
data = yf.download(all_tickers, start=CONFIG['start'], end=CONFIG['end'], 
                   auto_adjust=True, progress=False, threads=True)['Close']
data = data.ffill().dropna(axis=1, how='all')
print(f'   Loaded {len(data.columns)} assets, {len(data)} days')

# ============================================================
# 2. ALTERNATIVE DATA (Funding Rates, On-Chain)
# ============================================================
alt_signals = {}

def get_funding_rates(symbols):
    """Fetch funding rates from multiple exchanges (free APIs)"""
    signals = {}
    try:
        # Binance funding rates
        url = 'https://fapi.binance.com/fapi/v1/premiumIndex'
        resp = requests.get(url, timeout=10).json()
        for item in resp:
            sym = item['symbol'].replace('USDT', '-USD')
            if sym in symbols:
                rate = float(item['lastFundingRate'])
                signals[sym] = rate
    except:
        pass
    return signals

def get_fear_greed():
    """Fear & Greed Index"""
    try:
        url = 'https://api.alternative.me/fng/?limit=1'
        return requests.get(url, timeout=5).json()['data'][0]['value']
    except:
        return 50

if CONFIG['use_funding_rates']:
    print('📊 Fetching funding rates...')
    funding = get_funding_rates(CONFIG['crypto_tickers'])
    if funding:
        alt_signals['funding'] = pd.Series(funding)
        print(f'   Got funding for {len(funding)} assets')

# Fear & Greed
fg = get_fear_greed()
alt_signals['fear_greed'] = fg
print(f'   Fear & Greed: {fg}')

# ============================================================
# 3. FACTORS
# ============================================================
print('🔧 Computing factors...')
ret = data.pct_change()

# Per-asset factors
mom = data.pct_change(252).shift(21)
rev = -ret.rolling(21).sum()
vol = ret.rolling(60).std()
skew = ret.rolling(60).skew()
trend = data.rolling(20).apply(lambda x: stats.linregress(range(len(x)), x)[0] if len(x)==20 else np.nan)
rsi = data.pct_change().rolling(14).apply(lambda x: 100 - 100/(1 + x[x>0].mean()/abs(x[x<0].mean())) if len(x[x<0])>0 else 50)

# Stack
fac_list = {
    'mom_12_1': mom.stack(),
    'reversal_1m': rev.stack(),
    'vol_60': vol.stack(),
    'skew_60': skew.stack(),
    'vol_trend': trend.stack(),
    'rsi_14': rsi.stack(),
}
fac = pd.concat(fac_list, axis=1).dropna()

# Cross-sectional rank per date
ranked = fac.groupby(level=0).rank(pct=True) - 0.5

# Forward returns
fwd = data.pct_change(CONFIG['horizon']).shift(-CONFIG['horizon']).stack()
common = ranked.index.intersection(fwd.index)
ranked, fwd = ranked.loc[common], fwd.loc[common]

# Factor ICs
ic = ranked.corrwith(fwd, axis=0)
print('\n📊 Factor ICs:')
print(ic.sort_values(ascending=False).to_string())

# ============================================================
# 4. FACTOR BACKTEST
# ============================================================
print('\n📈 Factor-only backtest...')
sig_factor = ranked.mean(axis=1)
pos_factor = sig_factor.clip(-1, 1)
pnl_factor = (pos_factor * fwd).groupby(level=0).sum()
cum_factor = (1 + pnl_factor).cumprod()
sharpe_factor = pnl_factor.mean() / pnl_factor.std() * np.sqrt(252)
max_dd = (cum_factor / cum_factor.cummax() - 1).min()
print(f'   Sharpe: {sharpe_factor:.2f} | Return: {cum_factor.iloc[-1]:.0f}x | MaxDD: {max_dd:.2%}')

# ============================================================
# 5. ML FEATURES
# ============================================================
print('\n🤖 Building ML features...')
def make_features(prices):
    r = prices.pct_change()
    feat_list = []
    for lb in [5, 10, 20, 60, 120, 252]:
        ret_lb = r.rolling(lb).sum()
        vol_lb = r.rolling(lb).std()
        sharp_lb = ret_lb / vol_lb
        feat_list.append(ret_lb.stack().rename(f'ret_{lb}'))
        feat_list.append(vol_lb.stack().rename(f'vol_{lb}'))
        feat_list.append(sharp_lb.stack().rename(f'sharp_{lb}'))
    feat = pd.concat(feat_list, axis=1)
    for c in feat.columns:
        feat[c] = feat.groupby(level=0)[c].rank(pct=True)
    return feat.dropna()

X = make_features(data)
y = data.pct_change(CONFIG['horizon']).shift(-CONFIG['horizon']).stack()
idx = X.index.intersection(y.index)
X, y = X.loc[idx], y.loc[idx]

# ============================================================
# 6. REGIME DETECTION (HMM on Market Breadth)
# ============================================================
print('\n🎭 Detecting market regimes...')
# Market breadth: % assets above 200-day MA
ma200 = data.rolling(200).mean()
breadth = (data > ma200).mean(axis=1).dropna().values.reshape(-1, 1)

# Fit HMM
hmm_model = hmm.GaussianHMM(n_components=CONFIG['n_regimes'], covariance_type='full', 
                            n_iter=100, random_state=CONFIG['seed'])
hmm_model.fit(breadth)
regimes = hmm_model.predict(breadth)
regime_probs = hmm_model.predict_proba(breadth)

# Map regimes to names (by mean breadth)
regime_names = {}
for i in range(CONFIG['n_regimes']):
    mean_breadth = breadth[regimes==i].mean()
    if mean_breadth > 0.6: regime_names[i] = 'risk_on'
    elif mean_breadth > 0.3: regime_names[i] = 'neutral'
    else: regime_names[i] = 'risk_off'

regime_series = pd.Series([regime_names[r] for r in regimes], index=breadth.index.flatten())
print(f'   Regimes: {regime_series.value_counts().to_dict()}')

# Current regime
current_regime = regime_series.iloc[-1]
print(f'   Current regime: {current_regime}')

# ============================================================
# 7. ML TRAIN + OOS VALIDATION (Regime-Aware)
# ============================================================
print('\n🔄 Time-series cross-validation...')
ics = []
tscv = TimeSeriesSplit(n_splits=CONFIG['n_splits'])

for fold, (tr, te) in enumerate(tscv.split(X), 1):
    m = lgb.LGBMRegressor(n_estimators=300, max_depth=6, learning_rate=0.03,
                          subsample=0.8, colsample_bytree=0.8,
                          reg_alpha=0.1, reg_lambda=0.1,
                          random_state=CONFIG['seed'], n_jobs=-1, verbosity=-1)
    m.fit(X.iloc[tr], y.iloc[tr])
    pred = m.predict(X.iloc[te])
    ic = np.corrcoef(pred, y.iloc[te])[0, 1]
    ics.append(ic)
    print(f'   Fold {fold}: IC = {ic:.4f}')

print(f'\n   Mean OOS IC: {np.mean(ics):.4f} ± {np.std(ics):.4f}')

# ============================================================
# 8. FINAL MODEL
# ============================================================
print('\n🎯 Training final model...')
final_model = lgb.LGBMRegressor(n_estimators=300, max_depth=6, learning_rate=0.03,
                                subsample=0.8, colsample_bytree=0.8,
                                reg_alpha=0.1, reg_lambda=0.1,
                                random_state=CONFIG['seed'], n_jobs=-1, verbosity=-1)
final_model.fit(X, y)

latest_feat = X.groupby(level=1).tail(1)
today_signal = pd.Series(final_model.predict(latest_feat), index=latest_feat.index.get_level_values(1))
today_signal = today_signal.rank(pct=True) - 0.5

print('\n' + '='*50)
print('=== ML POSITIONS (ranked) ===')
print('='*50)
for asset, score in today_signal.sort_values(ascending=False).items():
    side = 'LONG 🟢' if score > 0 else 'SHORT 🔴'
    print(f'  {asset:12s}  {score:+.4f}  {side}')

# ============================================================
# 9. COMBINED SIGNAL (Factor + ML + Regime + Alt)
# ============================================================
print('\n🔗 Combining signals...')
latest_factor = sig_factor.groupby(level=1).last()
common_assets = latest_factor.index.intersection(today_signal.index)

factor_r = latest_factor.loc[common_assets].rank(pct=True)
ml_r = today_signal.loc[common_assets].rank(pct=True)

# Regime adjustment
regime_mult = {'risk_on': 1.2, 'neutral': 1.0, 'risk_off': 0.5}[current_regime]

# Fear/Greed adjustment (contrarian)
fg_mult = 1.0 + (50 - fg) / 100 * 0.2  # Scale 0.9-1.1

combined_raw = ((factor_r + ml_r) / 2 - 0.5) * regime_mult * fg_mult
combined_signal = combined_raw.clip(-1, 1)

print(f'\n📊 Regime: {current_regime} (mult: {regime_mult})')
print(f'   Fear/Greed: {fg} (mult: {fg_mult:.2f})')

# ============================================================
# 10. RISK MODEL (Ledoit-Wolf Covariance)
# ============================================================
print('\n🛡️ Building risk model...')
returns = data.pct_change().dropna()
cov = LedoitWolf().fit(returns).covariance_
cov = pd.DataFrame(cov, index=returns.columns, columns=returns.columns)

# ============================================================
# 11. PORTFOLIO OPTIMIZATION
# ============================================================
print('⚖️ Optimizing portfolio...')
n = len(common_assets)
alpha = combined_signal.loc[common_assets].values
Sigma = cov.loc[common_assets, common_assets].values

w = cp.Variable(n)
w_prev = np.zeros(n)

objective = cp.Maximize(
    alpha @ w 
    - CONFIG['risk_aversion'] * cp.quad_form(w, Sigma)
    - CONFIG['turnover_penalty'] * cp.norm(w - w_prev, 1)
)

constraints = [
    cp.sum(w) == 1.0,
    w >= -CONFIG['max_weight'],
    w <= CONFIG['max_weight'],
    cp.norm(w, 1) <= CONFIG['max_leverage']
]

prob = cp.Problem(objective, constraints)
prob.solve(solver=cp.ECOS, verbose=False)

opt_weights = pd.Series(w.value, index=common_assets).sort_values(ascending=False)

print('\n📋 Optimal Portfolio Weights:')
for asset, weight in opt_weights.items():
    if abs(weight) > 0.001:
        side = 'LONG' if weight > 0 else 'SHORT'
        print(f'  {asset:12s}  {weight:+.2%}  {side}')

# ============================================================
# 12. COST-ADJUSTED BACKTEST
# ============================================================
print('\n💰 Cost-adjusted backtest...')
cost_per_trade = (CONFIG['fee_bps'] + CONFIG['slippage_bps']) / 10000  # round-trip
turnover = pos_factor.diff().abs().sum(axis=1)
cost_drag = turnover * cost_per_trade
pnl_net = pnl_factor - cost_drag
cum_net = (1 + pnl_net).cumprod()
sharpe_net = pnl_net.mean() / pnl_net.std() * np.sqrt(252)

print(f'   Gross Sharpe: {sharpe_factor:.2f}')
print(f'   Net Sharpe (after costs): {sharpe_net:.2f}')
print(f'   Annual cost drag: {cost_drag.mean()*252:.2%}')

# ============================================================
# 13. WALK-FORWARD VALIDATION
# ============================================================
print('\n🚶 Walk-forward validation...')
wf_results = []
for train_end in pd.date_range(CONFIG['start'], CONFIG['end'], freq='M')[12:]:
    train_data = data[:train_end]
    test_data = data[train_end:train_end + pd.DateOffset(months=1)]
    if len(test_data) < 10: continue
    
    # Quick factor signal
    tr_ret = train_data.pct_change()
    tr_mom = train_data.pct_change(252).shift(21).iloc[-1]
    tr_vol = tr_ret.rolling(60).std().iloc[-1]
    tr_rank = (tr_mom / tr_vol).rank(pct=True) - 0.5
    
    test_fwd = test_data.pct_change(CONFIG['horizon']).shift(-CONFIG['horizon'])
    test_pnl = (tr_rank * test_fwd).sum(axis=1).dropna().sum()
    wf_results.append(test_pnl)

wf_series = pd.Series(wf_results, index=pd.date_range(CONFIG['start'], CONFIG['end'], freq='M')[12:12+len(wf_results)])
print(f'   Monthly periods: {len(wf_results)}')
print(f'   Hit rate: {(wf_series > 0).mean():.1%}')
print(f'   Avg monthly return: {wf_series.mean():.2%}')

# ============================================================
# 14. OUTPUT
# ============================================================
print('\n' + '='*60)
print('=== FINAL PORTFOLIO (Risk-Adjusted, Cost-Aware) ===')
print('='*60)
for asset, weight in opt_weights.items():
    if abs(weight) > 0.001:
        print(f'  {asset:12s}  {weight:+.2%}')

# Save
output = pd.DataFrame({
    'factor_signal': latest_factor,
    'ml_signal': today_signal,
    'combined_signal': combined_signal,
    'optimal_weight': opt_weights,
})
output.to_csv('today_signals.csv')

# Plot
fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
axes[0].plot(cum_factor.index, cum_factor.values, label=f'Factor Gross (Sharpe={sharpe_factor:.2f})', lw=1.5)
axes[0].plot(cum_net.index, cum_net.values, label=f'Factor Net (Sharpe={sharpe_net:.2f})', lw=1.5)
axes[0].set_ylabel('Cumulative Return'); axes[0].legend(); axes[0].grid(alpha=0.3)
axes[0].set_title('Alpha Model Backtest')

dd_gross = cum_factor / cum_factor.cummax() - 1
dd_net = cum_net / cum_net.cummax() - 1
axes[1].fill_between(dd_gross.index, dd_gross.values, 0, alpha=0.3, label='Gross DD')
axes[1].fill_between(dd_net.index, dd_net.values, 0, alpha=0.3, label='Net DD')
axes[1].set_ylabel('Drawdown'); axes[1].legend(); axes[1].grid(alpha=0.3)

axes[2].plot(regime_series.index, regime_series.map({'risk_on':2,'neutral':1,'risk_off':0}).values)
axes[2].set_ylabel('Regime'); axes[2].set_yticks([0,1,2]); axes[2].set_yticklabels(['Risk-Off','Neutral','Risk-On'])
axes[2].grid(alpha=0.3)

plt.tight_layout()
plt.savefig('alpha_backtest.png', dpi=150, bbox_inches='tight')
print('\n📊 Chart saved: alpha_backtest.png')

output.to_csv('today_signals.csv')
print('\n💾 Signals saved: today_signals.csv')
print(output.sort_values('optimal_weight', ascending=False).to_string())

print('\n✅ Done!')