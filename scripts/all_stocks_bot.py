#!/usr/bin/env python3
"""
All-Listed-Stocks Fundamental Analysis Bot
==========================================
Fully automated, one-command fundamental analysis of ALL NSE-listed equities.

For each symbol it:
  1. Auto-discovers all NSE-listed equity symbols from NSE's public EQUITY_L.csv
  2. Pulls fundamentals via yfinance (price, market cap, P/E, P/B, EV/EBITDA,
     revenue, EBITDA, net income, margins, ROE, ROCE, debt/equity, current ratio,
     dividend yield, beta, 52-week range, shares outstanding, enterprise value)
  3. Computes derived metrics and flags (valuation band, profitability, leverage,
     liquidity, momentum vs 52-week range)
  4. Writes a per-stock JSON report and an aggregated CSV summary
  5. Prints a ranked table to stdout

NO stock-timing or directional calls. Factual metrics and flags only.

Usage:
  python3 all_stocks_bot.py                           # ALL NSE-listed equities (auto-discovered)
  python3 all_stocks_bot.py --limit 100               # only first 100 symbols (for testing)
  python3 all_stocks_bot.py --file symbols.txt        # custom symbol list
  python3 all_stocks_bot.py --outdir reports/         # custom output dir
  python3 all_stocks_bot.py --resume                  # resume from last checkpoint
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import yfinance as yf
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise SystemExit(
        "yfinance is required. Install with: pip install yfinance pandas requests"
    ) from exc

try:
    import pandas as pd
    import requests
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise SystemExit(
        "pandas and requests are required. Install with: pip install yfinance pandas requests"
    ) from exc


# ---------------------------------------------------------------------------
# NSE equity list source (public, no auth required)
# ---------------------------------------------------------------------------
NSE_EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

CHECKPOINT_FILE = ".all_stocks_checkpoint.json"

# Metrics endpoint (Office OS web server)
METRICS_URL = "http://127.0.0.1:8083/api/stocks"


# ---------------------------------------------------------------------------
# Default fallback universes
# ---------------------------------------------------------------------------
# NSE NIFTY 50 (only used if NSE auto-discovery fails)
DEFAULT_NSE_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "BHARTIARTL.NS", "ICICIBANK.NS",
    "INFY.NS", "ITC.NS", "SBIN.NS", "BAJFINANCE.NS", "HINDUNILVR.NS",
    "LT.NS", "AXISBANK.NS", "KOTAKBANK.NS", "HCLTECH.NS", "SUNPHARMA.NS",
    "MARUTI.NS", "TITAN.NS", "NTPC.NS", "TATAMOTORS.NS", "BAJAJFINSV.NS",
    "NESTLEIND.NS", "ULTRACEMCO.NS", "WIPRO.NS", "ONGC.NS", "TATASTEEL.NS",
    "GRASIM.NS", "COALINDIA.NS", "TECHM.NS", "ADANIENT.NS", "POWERGRID.NS",
    "INDUSINDBK.NS", "ASIANPAINT.NS", "JSWSTEEL.NS", "HINDALCO.NS",
    "BAJAJ-AUTO.NS", "BRITANNIA.NS", "CIPLA.NS", "DRREDDY.NS", "EICHERMOT.NS",
    "HEROMOTOCO.NS", "BPCL.NS", "HDFCLIFE.NS", "SBILIFE.NS", "TATACONSUM.NS",
    "DIVISLAB.NS", "APOLLOHOSP.NS", "TATAPOWER.NS", "ADANIPORTS.NS", "M&M.NS",
]

# US equities — liquid, widely covered names (no exchange suffix needed for yfinance)
DEFAULT_US_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "TSLA", "META", "BRK-B",
    "UNH", "JNJ", "XOM", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK", "ABBV",
    "PEP", "KO", "AVGO", "COST", "WMT", "DIS", "NFLX", "ADBE", "CRM", "CSCO",
    "ACN", "VZ", "TXN", "INTU", "QCOM", "AMD", "HON", "LOW", "ISRG", "UBER",
    "AMGN", "GS", "MM", "NKE", "CAT", "BA", "LMT", "UNH", "PFE", "TMO",
    "DHR", "SPGI", "COP", "SLB", "MCD", "SBUX", "NKE", "ICE", "PLD", "GILD",
]

# Crypto majors — yfinance USD pairs. Flags are derived from turnover and
# 52-week range; equity-only metrics (P/E, D/E, ROE) do not apply.
DEFAULT_CRYPTO_UNIVERSE = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    "ADA-USD", "DOGE-USD", "LINK-USD", "AVAX-USD", "DOT-USD",
]


# ---------------------------------------------------------------------------
# Symbol discovery
# ---------------------------------------------------------------------------
def discover_nse_symbols() -> list[str]:
    """Fetch all NSE-listed equity symbols from the public EQUITY_L.csv."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/csv,application/csv,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(NSE_EQUITY_LIST_URL, headers=headers, timeout=60)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] NSE auto-discovery failed ({exc}); falling back to NIFTY 50.")
        return DEFAULT_UNIVERSE

    # Parse CSV: SYMBOL,NAME OF COMPANY, SERIES, ...
    text = resp.text
    lines = text.strip().splitlines()
    if not lines:
        return DEFAULT_UNIVERSE

    header = lines[0].split(",")
    sym_idx = header.index("SYMBOL") if "SYMBOL" in header else 0
    series_idx = header.index(" SERIES") if " SERIES" in header else None

    symbols: list[str] = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) <= sym_idx:
            continue
        sym = parts[sym_idx].strip()
        if not sym:
            continue
        # Only include main equity series (EQ); skip BE, BT, etc. if column present
        if series_idx is not None and len(parts) > series_idx:
            series = parts[series_idx].strip()
            if series != "EQ":
                continue
        symbols.append(f"{sym}.NS")

    if not symbols:
        return DEFAULT_UNIVERSE
    return symbols


def universe_with_crypto(symbols: list[str]) -> list[str]:
    """Append the crypto majors to an equity universe.

    The crypto bots read their facts from the same published payload as the
    equity bots, so every run publishes both asset classes — otherwise a
    --market us run would leave the crypto bots with no facts at all.
    """
    combined = list(symbols)
    for symbol in DEFAULT_CRYPTO_UNIVERSE:
        if symbol not in combined:
            combined.append(symbol)
    return combined


def load_universe(path: Optional[str], limit: Optional[int], market: str = "nse") -> list[str]:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            symbols = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    elif market == "us":
        symbols = list(DEFAULT_US_UNIVERSE)
    elif market == "crypto":
        symbols = list(DEFAULT_CRYPTO_UNIVERSE)
    elif market == "both":
        symbols = discover_nse_symbols() + list(DEFAULT_US_UNIVERSE) + list(DEFAULT_CRYPTO_UNIVERSE)
    else:
        symbols = discover_nse_symbols()

    if limit is not None:
        symbols = symbols[:limit]
    return symbols


# ---------------------------------------------------------------------------
# Checkpoint / resume
# ---------------------------------------------------------------------------
def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_checkpoint(completed: list[str], results: list[dict]) -> None:
    data = {
        "completed": completed,
        "results_count": len(results),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_get(info: dict, key: str, default=None):
    v = info.get(key)
    return v if v is not None else default


def fmt_num(v, decimals: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(v, decimals: int = 1) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v)*100:,.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_cr(v) -> str:
    """Format a value in INR crore (assume input already in INR)."""
    if v is None:
        return "—"
    try:
        return f"{float(v)/1e7:,.1f}"
    except (TypeError, ValueError):
        return "—"


def band(value, low, high, label_low="Low", label_high="High", label_mid="Mid"):
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if v <= low:
        return label_low
    if v >= high:
        return label_high
    return label_mid


def _is_crypto(info_full: dict) -> bool:
    return (safe_get(info_full, "quoteType") or "").upper() == "CRYPTOCURRENCY"


def _crypto_volatility_30d(ticker) -> Optional[float]:
    """Annualized-ish stdev of 30d daily returns, in percent."""
    try:
        hist = ticker.history(period="1mo")
        closes = list(hist["Close"].dropna().astype(float))
        if len(closes) < 5:
            return None
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1]
        ]
        if len(returns) < 4:
            return None
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return round(var ** 0.5 * 100, 2)
    except Exception:  # noqa: BLE001 - volatility is optional context
        return None


def analyze_symbol(symbol: str) -> dict:
    """Fetch and analyze a single symbol. Returns a dict of metrics + flags."""
    ticker = yf.Ticker(symbol)
    info = ticker.fast_info or {}
    info_full = ticker.info or {}
    is_crypto = _is_crypto(info_full)
    asset_class = "crypto" if is_crypto else "equity"

    # --- Price / market data ---
    price = (
        safe_get(info, "regularMarketPrice")
        or safe_get(info, "currentPrice")
        or safe_get(info, "lastPrice")
        or safe_get(info_full, "regularMarketPrice")
        or safe_get(info_full, "currentPrice")
        or safe_get(info_full, "regularMarketPreviousClose")
    )
    previous_close = safe_get(info_full, "previousClose") or safe_get(info_full, "regularMarketPreviousClose")
    day_high = safe_get(info, "regularMarketDayHigh")
    day_low = safe_get(info, "regularMarketDayLow")
    # Crypto carries its 52-week range in info only — fast_info has no value.
    fifty_two_high = safe_get(info, "fiftyTwoWeekHigh") or safe_get(info_full, "fiftyTwoWeekHigh")
    fifty_two_low = safe_get(info, "fiftyTwoWeekLow") or safe_get(info_full, "fiftyTwoWeekLow")
    market_cap = safe_get(info_full, "marketCap")
    enterprise_value = safe_get(info_full, "enterpriseValue")
    shares = safe_get(info_full, "sharesOutstanding")
    beta = safe_get(info_full, "beta")
    dividend_yield = safe_get(info_full, "dividendYield")
    total_volume = (
        safe_get(info_full, "totalVolume")
        or safe_get(info_full, "volume")
        or safe_get(info_full, "regularMarketVolume")
        or safe_get(info, "lastVolume")
    )

    # --- Valuation ---
    pe = safe_get(info_full, "trailingPE")
    pe_forward = safe_get(info_full, "forwardPE")
    pb = safe_get(info_full, "priceToBook")
    ev_ebitda = safe_get(info_full, "enterpriseToEbitda")
    ps = safe_get(info_full, "priceToSalesTrailing12Months")
    peg = safe_get(info_full, "pegRatio")

    # --- Profitability ---
    revenue = safe_get(info_full, "totalRevenue")
    ebitda = safe_get(info_full, "ebitda")
    net_income = safe_get(info_full, "netIncomeToCommon")
    gross_margin = safe_get(info_full, "grossMargins")
    operating_margin = safe_get(info_full, "operatingMargins")
    profit_margin = safe_get(info_full, "profitMargins")
    roe = safe_get(info_full, "returnOnEquity")
    roa = safe_get(info_full, "returnOnAssets")

    # --- Balance sheet / leverage ---
    total_debt = safe_get(info_full, "totalDebt")
    total_equity = safe_get(info_full, "totalStockholderEquity")
    current_ratio = safe_get(info_full, "currentRatio")
    quick_ratio = safe_get(info_full, "quickRatio")
    debt_to_equity = safe_get(info_full, "debtToEquity")
    debt_to_equity_unit = "ratio"
    if debt_to_equity is not None:
        try:
            # Yahoo Finance quotes debt/equity as a percentage (e.g. 150 = 150%);
            # normalize to a ratio so flags and scoring use one consistent scale.
            debt_to_equity = float(debt_to_equity) / 100.0
        except (TypeError, ValueError):
            debt_to_equity = None
    if debt_to_equity is None and total_debt and total_equity:
        # Computed from balance-sheet totals: already a ratio, keep as-is.
        try:
            debt_to_equity = total_debt / total_equity
        except (TypeError, ZeroDivisionError):
            pass

    # --- Cash flow ---
    operating_cf = safe_get(info_full, "operatingCashflow")
    free_cf = safe_get(info_full, "freeCashflow")
    capex = safe_get(info_full, "capitalExpenditures")

    # --- Growth ---
    revenue_growth = safe_get(info_full, "revenueGrowth")
    earnings_growth = safe_get(info_full, "earningsGrowth")

    # --- Derived: price vs 52-week range ---
    pct_from_52w_high = None
    pct_from_52w_low = None
    if price and fifty_two_high:
        pct_from_52w_high = (price - fifty_two_high) / fifty_two_high
    if price and fifty_two_low:
        pct_from_52w_low = (price - fifty_two_low) / fifty_two_low

    # --- Flags (factual thresholds, not recommendations) ---
    turnover_ratio = None
    volatility_30d_pct = None
    if is_crypto:
        # Crypto has no P/E, D/E, ROE or margins — those are N/A, not zero.
        valuation_flag = "N/A"
        leverage_flag = "N/A"
        profitability_flag = "N/A"
        roe_flag = "N/A"
        if total_volume and market_cap:
            turnover_ratio = total_volume / market_cap
        liquidity_flag = band(
            turnover_ratio, 0.01, 0.05, "Tight", "Comfortable", "Adequate"
        )
        liquidity_basis = "turnover_ratio"
        volatility_30d_pct = _crypto_volatility_30d(ticker)
    else:
        valuation_flag = band(pe, 15, 30, "Cheap", "Expensive", "Fair")
        leverage_flag = band(debt_to_equity, 0.5, 1.5, "Low", "High", "Moderate")
        liquidity_flag = band(current_ratio, 1.0, 2.0, "Tight", "Comfortable", "Adequate")
        liquidity_basis = "current_ratio"
        profitability_flag = band(profit_margin, 0.05, 0.15, "Weak", "Strong", "Moderate")
        roe_flag = band(roe, 0.10, 0.20, "Low", "High", "Moderate")

    if pct_from_52w_high is not None:
        if pct_from_52w_high >= -0.10:
            momentum_flag = "Near 52W high"
        elif pct_from_52w_high <= -0.30:
            momentum_flag = "Deep below 52W high"
        else:
            momentum_flag = "Mid range"
    else:
        momentum_flag = "—"

    return {
        "symbol": symbol,
        "name": safe_get(info_full, "longName") or safe_get(info_full, "shortName") or symbol,
        "asset_class": asset_class,
        "sector": safe_get(info_full, "sector"),
        "industry": safe_get(info_full, "industry"),
        "price": price,
        "previous_close": previous_close,
        "day_high": day_high,
        "day_low": day_low,
        "fifty_two_high": fifty_two_high,
        "fifty_two_low": fifty_two_low,
        "pct_from_52w_high": pct_from_52w_high,
        "pct_from_52w_low": pct_from_52w_low,
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        "shares_outstanding": shares,
        "beta": beta,
        "dividend_yield": dividend_yield,
        "total_volume": total_volume,
        "pe_ttm": pe,
        "pe_forward": pe_forward,
        "pb": pb,
        "ev_ebitda": ev_ebitda,
        "ps": ps,
        "peg": peg,
        "revenue": revenue,
        "ebitda": ebitda,
        "net_income": net_income,
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "profit_margin": profit_margin,
        "roe": roe,
        "roa": roa,
        "total_debt": total_debt,
        "total_equity": total_equity,
        "debt_to_equity": debt_to_equity,
        "debt_to_equity_unit": debt_to_equity_unit,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "operating_cf": operating_cf,
        "free_cf": free_cf,
        "capex": capex,
        "revenue_growth": revenue_growth,
        "earnings_growth": earnings_growth,
        # Flags
        "valuation_flag": valuation_flag,
        "leverage_flag": leverage_flag,
        "liquidity_flag": liquidity_flag,
        "liquidity_basis": liquidity_basis,
        "profitability_flag": profitability_flag,
        "roe_flag": roe_flag,
        "momentum_flag": momentum_flag,
        # Crypto-specific context
        "turnover_ratio": turnover_ratio,
        "volatility_30d_pct": volatility_30d_pct,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


def print_report(results: list[dict]) -> None:
    """Print a ranked factual summary table."""
    print("\n" + "=" * 140)
    print("ALL-LISTED-STOCKS FUNDAMENTAL SNAPSHOT (factual metrics only — no directional calls)")
    print("=" * 140)

    header = (
        f"{'Symbol':<14} {'Price':>9} {'MktCap₹Cr':>11} {'P/E':>7} {'P/B':>6} "
        f"{'EV/EBITDA':>9} {'ROE%':>7} {'D/E':>6} {'CurrRatio':>9} {'ProfitM%':>8} "
        f"{'52W High%':>10} {'Valuation':<9} {'Leverage':<9} {'Liquidity':<10}"
    )
    print(header)
    print("-" * 140)

    for r in sorted(results, key=lambda x: (x.get("market_cap") or 0), reverse=True):
        print(
            f"{r['symbol']:<14} "
            f"{fmt_num(r['price'], 2):>9} "
            f"{fmt_cr(r['market_cap']):>11} "
            f"{fmt_num(r['pe_ttm'], 1):>7} "
            f"{fmt_num(r['pb'], 1):>6} "
            f"{fmt_num(r['ev_ebitda'], 1):>9} "
            f"{fmt_pct(r['roe'], 1):>7} "
            f"{fmt_num(r['debt_to_equity'], 1):>6} "
            f"{fmt_num(r['current_ratio'], 1):>9} "
            f"{fmt_pct(r['profit_margin'], 1):>8} "
            f"{fmt_pct(r['pct_from_52w_high'], 1):>10} "
            f"{r['valuation_flag']:<9} {r['leverage_flag']:<9} {r['liquidity_flag']:<10}"
        )

    print("-" * 140)
    print(f"Total symbols analyzed: {len(results)}")
    print("Flags: Cheap/Fair/Expensive (P/E ≤15 / 15-30 / ≥30), "
          "Low/Moderate/High (D/E ≤0.5 / 0.5-1.5 / ≥1.5), "
          "Tight/Adequate/Comfortable (current ratio ≤1 / 1-2 / ≥2).")


def write_outputs(results: list[dict], outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Aggregated CSV
    csv_path = os.path.join(outdir, f"all_stocks_summary_{ts}.csv")
    flat_fields = [
        "symbol", "name", "sector", "industry", "price", "market_cap",
        "pe_ttm", "pb", "ev_ebitda", "roe", "debt_to_equity", "current_ratio",
        "profit_margin", "pct_from_52w_high", "valuation_flag", "leverage_flag",
        "liquidity_flag", "momentum_flag", "analyzed_at",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=flat_fields, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)

    # Per-symbol JSON
    for r in results:
        sym_safe = r["symbol"].replace(".", "_")
        json_path = os.path.join(outdir, f"{sym_safe}_{ts}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2, default=str)

    print(f"\nOutputs written to: {outdir}/")
    print(f"  Aggregated CSV: {os.path.basename(csv_path)}")
    print(f"  Per-symbol JSON: {len(results)} files")


def symbol_aliases(symbol: str) -> list[str]:
    """Every spelling bots use for one instrument, canonical first."""
    sym = symbol.strip()
    aliases = [sym]
    if sym.endswith(".NS"):
        aliases.append(sym[:-3])
    elif "-" in sym and sym.rsplit("-", 1)[-1] == "USD":
        base = sym.rsplit("-", 1)[0]
        aliases += [
            f"{base}/USD",
            f"{base}USD",
            f"{base}USDT",
            f"{base}/USDT",
            base,
        ]
    elif "-" in sym:
        aliases.append(sym.replace("-", "."))
    return aliases


def build_alias_map(results: list[dict]) -> dict:
    """Map every known symbol spelling to its facts entry.

    The producer owns the symbol vocabulary; consumers do a plain dict lookup.
    """
    facts_fields = (
        "symbol", "name", "asset_class", "market_cap", "price",
        "valuation_flag", "leverage_flag", "liquidity_flag", "liquidity_basis",
        "profitability_flag", "roe_flag", "momentum_flag",
        "turnover_ratio", "volatility_30d_pct", "analyzed_at",
        "debt_to_equity", "debt_to_equity_unit",
    )
    alias_map: dict[str, dict] = {}
    for r in results:
        if r.get("error"):
            continue
        entry = {f: r.get(f) for f in facts_fields}
        for alias in symbol_aliases(r.get("symbol") or ""):
            alias_map.setdefault(alias, entry)
    return alias_map


def push_metrics(results: list[dict], market: str = "nse") -> None:
    """Push a compact stock run summary to the Office OS metrics endpoint.

    POSTs to 127.0.0.1:8083/api/stocks so the /metrics dashboard
    shows the last stock analysis run. Fails silently — never
    blocks the bot run itself. Full per-symbol results remain on disk
    in the outdir; only a summary is sent over the wire.
    """
    try:
        flag_fields = (
            "valuation_flag", "leverage_flag", "liquidity_flag",
            "profitability_flag", "roe_flag", "momentum_flag",
        )
        flag_counts: dict[str, dict[str, int]] = {f: {} for f in flag_fields}
        equity_top: list[dict] = []
        crypto_top: list[dict] = []
        errors = 0

        for r in results:
            if r.get("error"):
                errors += 1
                continue
            for f in flag_fields:
                v = r.get(f) or "—"
                flag_counts[f][v] = flag_counts[f].get(v, 0) + 1
            summary = {
                "symbol": r.get("symbol"),
                "name": r.get("name"),
                "asset_class": r.get("asset_class", "equity"),
                "market_cap": r.get("market_cap"),
                "valuation_flag": r.get("valuation_flag"),
            }
            if r.get("asset_class") == "crypto":
                crypto_top.append(summary)
            else:
                equity_top.append(summary)
        equity_top.sort(key=lambda x: (x.get("market_cap") or 0), reverse=True)
        crypto_top.sort(key=lambda x: (x.get("market_cap") or 0), reverse=True)
        equity_top = equity_top[:10]
        crypto_top = crypto_top[:10]

        payload = {
            "service": "all-stocks-bot",
            "status": "ok",
            "market": market,
            "symbols_analyzed": len(results),
            "errors": errors,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "flag_counts": flag_counts,
            "top_by_market_cap": equity_top,
            "top_crypto_by_market_cap": crypto_top,
            "fundamentals_by_symbol": build_alias_map(results),
        }
        resp = requests.post(METRICS_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"[metrics] Stock summary pushed to {METRICS_URL} ({len(results)} symbols)")
        else:
            print(f"[warn] Metrics endpoint returned {resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Could not push stock metrics to {METRICS_URL}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated fundamental analysis of ALL NSE-listed equities."
    )
    parser.add_argument("--file", help="Path to a file with one symbol per line")
    parser.add_argument("--limit", type=int, help="Max symbols to analyze (for testing)")
    parser.add_argument("--market", choices=["nse", "us", "crypto", "both"], default="nse",
                        help="Market universe: nse (default), us, crypto, or both")
    parser.add_argument("--outdir", default="reports", help="Output directory (default: reports/)")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument("--rate-limit", type=float, default=0.5,
                        help="Seconds to wait between yfinance calls (default: 0.5)")
    args = parser.parse_args()

    universe = load_universe(args.file, args.limit, args.market)
    if not args.file and args.market != "crypto":
        universe = universe_with_crypto(universe)
    print(f"Universe size: {len(universe)} symbols (auto-discovered from NSE EQUITY_L.csv)")

    # Resume support
    completed = set()
    results = []
    start_index = 0
    if args.resume:
        ckpt = load_checkpoint()
        completed = set(ckpt.get("completed", []))
        # Re-load prior results if available
        # (We re-fetch; checkpoint mainly tracks what's done to avoid rework on next run)
        if completed:
            print(f"Resuming: {len(completed)} symbols already completed.")
            universe = [s for s in universe if s not in completed]
            start_index = len(completed)

    print(f"Analyzing {len(universe)} symbols via yfinance... (rate limit: {args.rate_limit}s)\n")

    for i, symbol in enumerate(universe, start_index + 1):
        print(f"[{i}/{start_index + len(universe)}] {symbol} ...", end=" ", flush=True)
        try:
            r = analyze_symbol(symbol)
            results.append(r)
            completed.add(symbol)
            print("✓")
        except Exception as exc:  # noqa: BLE001 - continue on individual failures
            print(f"✗ ({exc})")
            results.append({
                "symbol": symbol,
                "error": str(exc),
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            })
            completed.add(symbol)

        # Rate limiting to avoid hammering yfinance
        if i < start_index + len(universe):
            time.sleep(args.rate_limit)

        # Periodic checkpoint
        if i % 50 == 0:
            save_checkpoint(sorted(completed), results)

    if results:
        # Merge with any prior results from checkpoint run
        print_report(results)
        write_outputs(results, args.outdir)
        push_metrics(results, args.market)
        save_checkpoint(sorted(completed), results)
        print(f"\nCheckpoint saved: {len(completed)} total symbols completed.")


if __name__ == "__main__":
    main()
