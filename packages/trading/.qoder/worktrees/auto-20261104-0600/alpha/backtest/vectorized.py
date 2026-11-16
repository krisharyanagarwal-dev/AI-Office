"""
Vectorized Backtest Engine
High-performance vectorized backtesting for systematic strategies
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Union, Callable
from datetime import datetime, timedelta
import yaml
import logging
from pathlib import Path

from alpha.data.providers import YFinanceProvider, AlphaVantageProvider, PolygonProvider, BinanceProvider, CompositeProvider
from alpha.portfolio.optimization import MeanVarianceOptimizer, MinVarianceOptimizer, MaxSharpeOptimizer, RiskParityOptimizer, EqualWeightOptimizer
from alpha.risk.risk_manager import RiskManager
from alpha.validation.walkforward import WalkForwardValidator
from alpha.backtest.cost_model import cost_sensitivity

logger = logging.getLogger(__name__)


class VectorizedBacktester:
    """
    Vectorized backtester for systematic strategies
    
    Features:
    - Vectorized operations for speed
    - Multi-asset portfolio support
    - Transaction cost modeling
    - Flexible signal generation
    - Performance attribution
    - Risk-adjusted metrics
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize vectorized backtester
        
        Args:
            config_path: Path to configuration file (default: config/settings.yaml)
        """
        self.config_path = config_path or "/Users/aryanagarwal/alpha-system/config/settings.yaml"
        self.config = self._load_config()
        self._setup_universe()
        self._setup_providers()
        self.results = {}
        
    def _load_config(self) -> Dict:
        """Load configuration from YAML file"""
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config
    
    def _setup_universe(self):
        """Setup trading universe from configuration"""
        self.universe = {}
        if 'universe' in self.config:
            for asset_class, symbols in self.config['universe'].items():
                self.universe[asset_class] = symbols
                
        # Flatten universe for easy access
        self.symbols = []
        for asset_class, symbols in self.universe.items():
            self.symbols.extend(symbols)
            
        logger.info(f"Universe loaded: {len(self.symbols)} symbols across {len(self.universe)} asset classes")
    
    def _setup_providers(self):
        """Setup data providers with graceful failure handling"""
        providers = []

        # Try to initialize each provider, skip those that fail
        try:
            providers.append(YFinanceProvider())
            logger.debug("YFinanceProvider initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize YFinanceProvider: {e}")

        try:
            providers.append(AlphaVantageProvider())
            logger.debug("AlphaVantageProvider initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize AlphaVantageProvider: {e}")

        try:
            providers.append(PolygonProvider())
            logger.debug("PolygonProvider initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize PolygonProvider: {e}")

        try:
            providers.append(BinanceProvider())
            logger.debug("BinanceProvider initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize BinanceProvider: {e}")

        # Create composite provider with successfully initialized providers
        if providers:
            self.providers = CompositeProvider(providers)
            logger.info(f"Initialized {len(providers)} data providers")
        else:
            logger.warning("No data providers could be initialized")
            # Create an empty composite provider - will fail later if data fetching is attempted
            self.providers = CompositeProvider([])
    def fetch_data(self, 
                   symbols: Optional[List[str]] = None,
                   start_date: Optional[str] = None,
                   end_date: Optional[str] = None,
                   frequency: str = "1d") -> Dict[str, pd.DataFrame]:
        """
        Fetch historical data for backtesting
        
        Args:
            symbols: List of symbols to fetch (default: universe symbols)
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            frequency: Data frequency (1d, 1h, etc.)
            
        Returns:
            Dictionary mapping symbol to OHLCV DataFrame
        """
        symbols = symbols or self.symbols
        start_date = start_date or self.config.get('backtest', {}).get('start_date', '2020-01-01')
        end_date = end_date or self.config.get('backtest', {}).get('end_date', datetime.now().strftime('%Y-%m-%d'))
        
        logger.info(f"Fetching data for {len(symbols)} symbols from {start_date} to {end_date}")
        
        data = {}
        for symbol in symbols:
            try:
                df = self.providers.fetch(
                    tickers=[symbol],
                    start=start_date,
                    end=end_date,
                    frequency=frequency,
                    adjust=True
                )
                if df is not None and not df.empty:
                    data[symbol] = df
                else:
                    logger.warning(f"No data fetched for {symbol}")
            except Exception as e:
                logger.error(f"Error fetching data for {symbol}: {e}")
                
        logger.info(f"Successfully fetched data for {len(data)} symbols")
        return data
    
    def run_backtest(self,
                      signals: Dict[str, pd.Series],
                      data: Optional[Dict[str, pd.DataFrame]] = None,
                      initial_capital: Optional[float] = None,
                      rebalance_frequency: str = "1D",
                      max_position_size: Optional[float] = None,
                      stop_loss: Optional[float] = None,
                      take_profit: Optional[float] = None) -> Dict:
        """
        Run vectorized backtest
        
        Args:
            signals: Dictionary mapping symbol to signal series (1=long, -1=short, 0=neutral)
            data: Optional pre-fetched data (if not provided, will fetch)
            initial_capital: Starting capital (default from config)
            rebalance_frequency: How often to rebalance (1D, 1W, 1M)
            max_position_size: Maximum position size as fraction of capital
            stop_loss: Stop loss percentage
            take_profit: Take profit percentage
            
        Returns:
            Dictionary containing backtest results
        """
        # Set defaults
        initial_capital = initial_capital or self.config.get('backtest', {}).get('initial_capital', 1_000_000)
        
        # Fetch data if not provided
        if data is None:
            data = self.fetch_data()
            
        if not data:
            raise ValueError("No data available for backtesting")
            
        # Align all data to common timeline
        aligned_data, aligned_signals = self._align_data_signals(data, signals)
        
        # Calculate returns
        returns = self._calculate_returns(aligned_data)
        
        # Generate positions from signals
        positions = self._generate_positions(
            aligned_signals, 
            max_position_size=max_position_size
        )
        
        # Calculate P&L
        pnl = self._calculate_pnl(positions, returns, data)
        
        # Apply transaction costs
        pnl_after_costs, cost_totals = self._apply_transaction_costs(
            pnl, positions, data,
            commission=self.config.get('backtest', {}).get('costs', {}).get('commission', 0.0005),
            slippage=self.config.get('backtest', {}).get('costs', {}).get('slippage', 0.0003),
            spread=self.config.get('backtest', {}).get('costs', {}).get('spread', 0.0002)
        )

        # Calculate equity curve
        equity_curve = self._calculate_equity_curve(pnl_after_costs, initial_capital)

        # Calculate performance metrics
        metrics = self._calculate_metrics(equity_curve, returns, positions)

        # The same cost model the event-driven engine uses, so a gross figure can
        # never be published without the venue fee it has to survive.
        net_series = self._sum_series(pnl_after_costs)
        cost_block = cost_sensitivity(
            gross_pnl=cost_totals['gross'],
            costs=cost_totals['costs'],
            commission=cost_totals['commission_rate'],
            slippage=cost_totals['slippage_rate'],
            spread=cost_totals['spread_rate'],
            unit_values=list(net_series),
            basis='per bar (portfolio net return, costs already deducted)',
            non_fee_note='slippage + spread',
        )

        # Store results
        self.results = {
            'data': data,
            'signals': signals,
            'returns': returns,
            'positions': positions,
            'pnl': pnl,
            'pnl_after_costs': pnl_after_costs,
            'equity_curve': equity_curve,
            'metrics': metrics,
            'cost_totals': {k: float(v) for k, v in cost_totals.items()},
            'cost_sensitivity': cost_block,
            'initial_capital': initial_capital,
            'config': self.config
        }

        return self.results

    @staticmethod
    def _sum_series(pnl_by_symbol: Dict[str, pd.Series]) -> pd.Series:
        """Portfolio P&L per bar, summed across symbols in the engine's own units."""
        total = None
        for pnl_series in pnl_by_symbol.values():
            total = pnl_series if total is None else total.add(pnl_series, fill_value=0)
        if total is None:
            return pd.Series(dtype=float)
        return total.fillna(0)

    def _align_data_signals(self, 
                            data: Dict[str, pd.DataFrame],
                            signals: Dict[str, pd.Series]) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.Series]]:
        """Align data and signals to common timeline"""
        # Get all unique dates across all symbols
        all_dates = set()
        for symbol, df in data.items():
            all_dates.update(df.index)
        
        common_index = sorted(all_dates)
        
        # Align data
        aligned_data = {}
        for symbol, df in data.items():
            aligned_data[symbol] = df.reindex(common_index).ffill()
        
        # Align signals
        aligned_signals = {}
        for symbol, signal in signals.items():
            if symbol in data:
                aligned_signals[symbol] = signal.reindex(common_index).fillna(0)
            else:
                aligned_signals[symbol] = pd.Series(0, index=common_index)
                
        return aligned_data, aligned_signals

    def _calculate_returns(self,
                            data: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        returns = {}
        for symbol, df in data.items():
            # Use close prices for returns
            if 'close' in df.columns:
                price = df['close']
            elif 'Close' in df.columns:
                price = df['Close']
            else:
                # Use first column if no close column
                price = df.iloc[:, 0]
                
            returns[symbol] = price.pct_change().fillna(0)
        return returns
    
    def _generate_positions(self, 
                           signals: Dict[str, pd.Series],
                           max_position_size: Optional[float] = None) -> Dict[str, pd.Series]:
        """Generate position sizes from signals"""
        positions = {}
        max_pos = max_position_size or 1.0  # Default to full position
        
        for symbol, signal in signals.items():
            # Apply position size limits
            position = signal.clip(-max_pos, max_pos)
            positions[symbol] = position
            
        return positions
    
    def _calculate_pnl(self, 
                      positions: Dict[str, pd.Series],
                      returns: Dict[str, pd.Series],
                      data: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Calculate P&L from positions and returns"""
        pnl = {}
        
        for symbol in positions.keys():
            if symbol in returns and symbol in data:
                # Get position from previous period (to avoid lookahead bias)
                pos = positions[symbol].shift(1).fillna(0)
                ret = returns[symbol]
                
                # Calculate P&L
                pnl[symbol] = pos * ret
            else:
                pnl[symbol] = pd.Series(0, index=positions[symbol].index)
                
        return pnl
    
    def _apply_transaction_costs(self,
                                pnl: Dict[str, pd.Series],
                                positions: Dict[str, pd.Series],
                                data: Dict[str, pd.DataFrame],
                                commission: float = 0.0005,
                                slippage: float = 0.0003,
                                spread: float = 0.0002) -> Tuple[Dict[str, pd.Series], Dict[str, float]]:
        """Apply transaction costs to P&L and report what they came to.

        Returns ``(pnl_after_costs, totals)`` where ``totals`` is in the engine's
        own units (per-bar simple returns summed over bars and symbols) plus the
        three rates that produced them, so the cost figure can be audited and
        re-netted at another venue instead of being a bare subtraction.
        """
        pnl_after_costs = {}
        gross_total = 0.0
        cost_total = 0.0
        turnover_total = 0.0

        for symbol in pnl.keys():
            if symbol in positions and symbol in data:
                # Calculate turnover (absolute change in position)
                turnover = positions[symbol].diff().abs().fillna(0)

                # Costs, all proportional to turnover:
                #   commission: flat rate per trade
                #   slippage: simplified to a fixed percentage of turnover
                #   spread: half spread per trade, likewise on turnover
                cost_rate = commission + slippage + spread
                total_costs = turnover * cost_rate
                turnover_total += float(turnover.sum())
            else:
                total_costs = pd.Series(0.0, index=pnl[symbol].index)

            gross_total += float(pnl[symbol].sum())
            cost_total += float(total_costs.sum())
            pnl_after_costs[symbol] = pnl[symbol] - total_costs

        totals = {
            'gross': gross_total,
            'costs': cost_total,
            'turnover': turnover_total,
            'commission_rate': commission,
            'slippage_rate': slippage,
            'spread_rate': spread,
            'cost_rate_per_side': commission + slippage + spread,
        }
        return pnl_after_costs, totals
    
    def _calculate_equity_curve(self, 
                               pnl_after_costs: Dict[str, pd.Series],
                               initial_capital: float) -> pd.Series:
        """Calculate equity curve from P&L"""
        # Sum P&L across all symbols
        total_pnl = pd.Series(0, index=next(iter(pnl_after_costs.values())).index)
        
        for symbol, pnl_series in pnl_after_costs.items():
            total_pnl = total_pnl.add(pnl_series, fill_value=0)
        
        # Calculate equity curve
        equity_curve = initial_capital * (1 + total_pnl.cumsum())
        
        return equity_curve
    
    def _calculate_metrics(self, 
                          equity_curve: pd.Series,
                          returns: Dict[str, pd.Series],
                          positions: Dict[str, pd.Series]) -> Dict[str, float]:
        """Calculate performance metrics"""
        if len(equity_curve) < 2:
            return {}
            
        # Calculate returns
        returns_series = equity_curve.pct_change().fillna(0)
        
        # Basic metrics
        total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1
        annualized_return = (1 + total_return) ** (252 / len(returns_series)) - 1
        
        # Volatility
        volatility = returns_series.std() * np.sqrt(252)
        
        # Sharpe ratio (assuming 0% risk-free rate)
        sharpe_ratio = annualized_return / volatility if volatility > 0 else 0
        
        # Sortino ratio
        downside_returns = returns_series[returns_series < 0]
        downside_deviation = downside_returns.std() * np.sqrt(252) if len(downside_returns) > 0 else 0
        sortino_ratio = annualized_return / downside_deviation if downside_deviation > 0 else 0
        
        # Maximum drawdown
        rolling_max = equity_curve.expanding().max()
        drawdown = (equity_curve - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        
        # Calmar ratio
        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0
        
        # Win rate
        winning_days = (returns_series > 0).sum()
        total_days = len(returns_series)
        win_rate = winning_days / total_days if total_days > 0 else 0
        
        # Average win/loss
        avg_win = returns_series[returns_series > 0].mean() if (returns_series > 0).any() else 0
        avg_loss = returns_series[returns_series < 0].mean() if (returns_series < 0).any() else 0
        # Undefined, not infinite: with no losing bar there is no denominator, and
        # `inf` in a report reads as unbounded edge.
        profit_factor = float(abs(avg_win / avg_loss)) if avg_loss != 0 else (
            None if avg_win != 0 else 0.0)
        
        return {
            'total_return': total_return,
            'annualized_return': annualized_return,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'max_drawdown': max_drawdown,
            'calmar_ratio': calmar_ratio,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_days': total_days,
            'winning_days': winning_days
        }
    
    def get_results(self) -> Dict:
        """Get backtest results"""
        return self.results
    def plot_equity_curve(self, save_path: Optional[str] = None):
        """Plot equity curve"""
        try:
            import matplotlib.pyplot as plt
            
            if 'equity_curve' in self.results:
                plt.figure(figsize=(12, 6))
                plt.plot(self.results['equity_curve'].index, self.results['equity_curve'].values)
                plt.title('Equity Curve')
                plt.xlabel('Date')
                plt.ylabel('Equity ($)')
                plt.grid(True, alpha=0.3)
                
                if save_path:
                    plt.savefig(save_path, dpi=300, bbox_inches='tight')
                plt.show()
            else:
                logger.warning("No equity curve data to plot")
        except ImportError:
            logger.warning("Matplotlib not available for plotting")
    
    def get_tear_sheet(self) -> str:
        """Generate tear sheet summary"""
        if not self.results:
            return "No backtest results available"
            
        metrics = self.results.get('metrics', {})
        cs = self.results.get('cost_sensitivity') or {}
        totals = self.results.get('cost_totals') or {}
        sig = cs.get('significance') or {}
        be = cs.get('break_even_bps_per_side')
        be_display = f"{be:.1f} bps/side" if be is not None else 'no fee clears this book'
        pf = metrics.get('profit_factor', 0.0)
        pf_display = 'undefined (no losing bar)' if pf is None else f'{pf:.2f}'
        capital = self.results.get('initial_capital', 0)
        scenario_lines = '\n'.join(
            f"  {s['fee_bps_per_side']:>5.1f} bps/side ({s['label']}): "
            f"net {s['net_pnl']:+.6f} as a return share "
            f"(${s['net_pnl'] * capital:,.2f} on the initial capital) "
            f"{'clears' if s['clears'] else 'DOES NOT CLEAR'}"
            for s in cs.get('scenarios', [])
        )
        tear_sheet = f"""
BACKTEST TEAR SHEET
===================
Period: {self.results['equity_curve'].index[0].date()} to {self.results['equity_curve'].index[-1].date()}
Initial Capital: ${self.results.get('initial_capital', 0):,.2f}
Final Equity: ${self.results['equity_curve'].iloc[-1]:,.2f}

RETURNS (net of the modelled costs below)
-------
Total Return: {metrics.get('total_return', 0):.2%}
Annualized Return: {metrics.get('annualized_return', 0):.2%}
Volatility: {metrics.get('volatility', 0):.2%}
Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}
Sortino Ratio: {metrics.get('sortino_ratio', 0):.2f}
Calmar Ratio: {metrics.get('calmar_ratio', 0):.2f}

RISK METRICS
------------
Max Drawdown: {metrics.get('max_drawdown', 0):.2%}
Win Rate (share of positive BARS, not round trips): {metrics.get('win_rate', 0):.2%}
Profit Factor (mean positive bar / mean negative bar): {pf_display}

TRADE STATISTICS
----------------
Total Days: {metrics.get('total_days', 0)}
Winning Days: {metrics.get('winning_days', 0)}
Losing Days: {metrics.get('total_days', 0) - metrics.get('winning_days', 0)}

GROSS vs NET (sum of per-bar return shares, the engine's own units)
-------------------------------------------------------------------
Gross: {totals.get('gross', 0):+.6f}   Costs: {totals.get('costs', 0):.6f}   Net: {cs.get('net_pnl', 0):+.6f}
Turnover: {totals.get('turnover', 0):,.4f} units traded, at {cs.get('modelled_cost_bps_per_side', 0):.1f} bps/side
  = {cs.get('modelled_commission_bps_per_side', 0):.1f} bps commission
  + {cs.get('modelled_slippage_bps_per_side', 0):.1f} bps slippage
  + {cs.get('modelled_spread_bps_per_side', 0):.1f} bps spread
A round trip pays that twice: {cs.get('min_gross_bps_per_round_trip_to_break_even', 0):.1f} bps of gross edge per round trip is the floor.
Break-even fee: {be_display}
{scenario_lines}

MEANING OF THE CI
-----------------
{sig.get('n', 0)} bars, mean net per bar: {'n/a' if sig.get('mean') is None else f"{sig['mean']:+.8f}"} (return share)
95% CI: {sig.get('ci95_low') if sig.get('ci95_low') is not None else 'n/a'} to {sig.get('ci95_high') if sig.get('ci95_high') is not None else 'n/a'}
Tradeable claim allowed: {cs.get('tradeable_claim_allowed')}
Blocked by: {cs.get('claim_blockers') or 'nothing'}

COST ASSUMPTION
---------------
Venue assumed: {cs.get('venue', 'n/a')}
Note: the configured commission is {cs.get('modelled_commission_bps_per_side', 0):.1f} bps/side, {'BELOW' if cs.get('commission_below_venue_fee') else 'at or above'} the Binance VIP0 {10.0:g} bps a venue actually charges maker AND taker — slippage and spread are what close the gap here.
{cs.get('funding_note', '')}
"""
        return tear_sheet


# Convenience function for quick backtesting
def run_vectorized_backtest(signals: Dict[str, pd.Series], 
                           data: Optional[Dict[str, pd.DataFrame]] = None,
                           config_path: Optional[str] = None) -> Dict:
    """
    Convenience function to run vectorized backtest
    
    Args:
        signals: Dictionary mapping symbol to signal series
        data: Optional pre-fetched data
        config_path: Path to configuration file
        
    Returns:
        Backtest results dictionary
    """
    backtester = VectorizedBacktester(config_path)
    return backtester.run_backtest(signals, data)


if __name__ == "__main__":
    # Example usage
    import yfinance as yf
    
    # Example: Simple moving average crossover signal
    data = yf.download("SPY", start="2020-01-01", end="2023-12-31")
    data['SMA_50'] = data['Close'].rolling(50).mean()
    data['SMA_200'] = data['Close'].rolling(200).mean()
    data['signal'] = np.where(data['SMA_50'] > data['SMA_200'], 1, -1)
    
    signals = {'SPY': data['signal']}
    
    # Run backtest
    backtester = VectorizedBacktester()
    results = backtester.run_backtest(signals, {'SPY': data})
    
    # Print results
    print(backtester.get_tear_sheet())