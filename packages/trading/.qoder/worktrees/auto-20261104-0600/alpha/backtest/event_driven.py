"""
Event-driven backtester for systematic strategies

Features:
- Chronological processing of market data
- Event-driven architecture
- Realistic trade simulation
- Position tracking
- Performance metrics
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging


logger = logging.getLogger(__name__)

from alpha.backtest.cost_model import cost_sensitivity

def _record_round_trip(ledger, timestamp, symbol, direction, qty_closed, entry_price,
                       exit_price, gross, costs, kind):
    ledger.append({
        'timestamp': timestamp,
        'symbol': symbol,
        'direction': direction,
        'qty_closed': qty_closed,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'gross_pnl': gross,
        'costs': costs,
        'net_pnl': gross - costs,
        'kind': kind,
    })


def _apply_fill(state, timestamp, symbol, price, delta, cost, ledger):
    """Apply one fill to the open position and book any round trip it closes.

    ``cost`` is the commission + slippage charged on this fill's notional. It is
    split pro-rata between the leg that closes the old position and the leg that
    opens a new one, so a flip does not charge the whole cost to the closed leg.
    """
    qty = state['qty']
    if qty == 0.0 or (delta > 0) == (qty > 0):
        new_abs = abs(qty) + abs(delta)
        state['avg_price'] = (state['avg_price'] * abs(qty) + price * abs(delta)) / new_abs
        state['qty'] = qty + delta
        state['costs'] += cost
        return

    direction = 1.0 if qty > 0 else -1.0
    closed = min(abs(delta), abs(qty))
    gross = direction * (price - state['avg_price']) * closed
    costs = state['costs'] * (closed / abs(qty)) + cost * (closed / abs(delta))
    _record_round_trip(ledger, timestamp, symbol, direction, direction * closed,
                       state['avg_price'], price, gross, costs, 'close')

    state['qty'] = qty - direction * closed
    state['costs'] -= state['costs'] * (closed / abs(qty))

    leftover = delta + direction * closed
    if abs(leftover) > 1e-12:
        # The fill went through flat, so what remains opens a position at this price.
        state['qty'] = leftover
        state['avg_price'] = price
        state['costs'] = cost * (abs(leftover) / abs(delta))
    # A partial close leaves the surviving quantity on its original average entry.


class EventDrivenBacktester:
    """
    Event-driven backtester for systematic strategies
    
    Features:
    - Processes data chronologically (bar-by-bar)
    - Handles market events, signals, and orders
    - Tracks positions and performance in real-time
    - Supports multiple symbols
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize event-driven backtester
        
        Args:
            config_path: Path to configuration file (default: config/settings.yaml)
        """
        self.config_path = config_path or "/Users/aryanagarwal/alpha-system/config/settings.yaml"
        self.config = self._load_config()
        self.results = {}
        
    def _load_config(self) -> dict:
        """Load configuration from YAML file"""
        import yaml
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            config = {}
        return config
    
    def run_backtest(
        self,
        signals: Dict[str, pd.Series],
        data: Dict[str, pd.DataFrame],
        initial_capital: float = 100000,
        commission: float = 0.001,
        slippage: float = 0.0005
    ) -> Dict:
        """
        Run event-driven backtest
        
        Args:
            signals: Dictionary of symbol -> signal series (1 for long, -1 for short, 0 for neutral)
            data: Dictionary of symbol -> OHLCV DataFrame
            initial_capital: Starting capital
            commission: Commission rate per fill, as a fraction of traded notional
                (default: 0.001 = Binance VIP0 taker/maker 0.1%)
            slippage: Slippage rate per fill (default: 0.0005 = 0.05%)

        Costs are charged on every fill and the ``win_rate`` / ``net_pnl`` reported
        here are net of them. Perpetual funding is not modeled by this engine.

        Returns:
            Dictionary containing backtest results
        """
        logger.info("Starting event-driven backtest")
        
        # Validate inputs
        if not signals or not data:
            raise ValueError("Signals and data dictionaries cannot be empty")
        
        # Get common time index across all symbols
        common_index = self._get_common_index(data)
        if common_index.empty:
            raise ValueError("No common time index found across symbols")
        
        logger.info(f"Backtesting {len(data)} symbols from {common_index[0]} to {common_index[-1]}")
        
        # Initialize tracking variables
        positions = {symbol: 0.0 for symbol in data.keys()}  # Current position size
        open_state = {
            symbol: {'qty': 0.0, 'avg_price': 0.0, 'costs': 0.0}
            for symbol in data.keys()
        }
        round_trip_ledger = []
        cash = initial_capital
        equity_curve = []  # Track equity over time
        trades = []  # Track individual trades
        
        # Process each time step chronologically
        for timestamp in common_index:
            # Update market prices for current timestamp
            market_prices = {}
            for symbol, df in data.items():
                if timestamp in df.index:
                    # Use close price for simplicity (could use bid/ask spread)
                    market_prices[symbol] = df.loc[timestamp, 'close']
                else:
                    # Carry forward last known price
                    if symbol in market_prices:
                        pass  # Keep previous price
                    else:
                        # Find last available price before this timestamp
                        available_times = df.index[df.index <= timestamp]
                        if len(available_times) > 0:
                            market_prices[symbol] = df.loc[available_times[-1], 'close']
                        else:
                            market_prices[symbol] = 0.0  # No price data yet
            
            # Calculate current portfolio value
            position_value = sum(
                positions[symbol] * market_prices.get(symbol, 0) 
                for symbol in positions.keys()
            )
            current_equity = cash + position_value
            equity_curve.append({
                'timestamp': timestamp,
                'equity': current_equity,
                'cash': cash,
                'position_value': position_value
            })
            
            # Process signals and generate orders for each symbol
            for symbol in data.keys():
                if timestamp not in data[symbol].index:
                    continue
                    
                # Get current signal
                signal_value = 0
                if symbol in signals and timestamp in signals[symbol].index:
                    signal_value = signals[symbol].loc[timestamp]
                
                # Current position
                current_position = positions[symbol]
                current_price = market_prices.get(symbol, 0)
                
                # Calculate target position based on signal
                # Simple approach: signal = 1 -> long, signal = -1 -> short, signal = 0 -> flat
                # In a real system, this would be more sophisticated (position sizing, risk limits, etc.)
                target_position = signal_value  # Simplified: -1, 0, 1
                
                # Calculate trade size needed
                trade_size = target_position - current_position
                
                if abs(trade_size) > 1e-8:  # If we need to trade
                    # Calculate trade value
                    trade_value = abs(trade_size) * current_price
                    
                    # Calculate costs
                    commission_cost = trade_value * commission
                    slippage_cost = trade_value * slippage
                    total_cost = commission_cost + slippage_cost
                    
                    # Update cash (subtract trade value and costs)
                    cash -= trade_size * current_price  # Negative for buys, positive for sells
                    cash -= total_cost  # Always subtract costs
                    
                    # Update position
                    positions[symbol] = target_position
                    _apply_fill(open_state[symbol], timestamp, symbol, current_price,
                                trade_size, total_cost, round_trip_ledger)
                    
                    # Record trade
                    trades.append({
                        'timestamp': timestamp,
                        'symbol': symbol,
                        'trade_size': trade_size,
                        'price': current_price,
                        'value': trade_value,
                        'commission': commission_cost,
                        'slippage': slippage_cost,
                        'total_cost': total_cost,
                        'new_position': positions[symbol]
                    })
        
        # Calculate final equity
        final_prices = {}
        for symbol, df in data.items():
            if len(df) > 0:
                final_prices[symbol] = df.iloc[-1]['close']
            else:
                final_prices[symbol] = 0.0
        
        final_position_value = sum(
            positions[symbol] * final_prices.get(symbol, 0) 
            for symbol in positions.keys()
        )
        final_equity = cash + final_position_value
        
        # Positions still open at the last bar are marked so the ledger reconciles
        # with final_equity, but a mark is NOT a closed trade: it is kept out of the
        # realized statistics and reported as its own unrealized block.
        open_positions = {}
        for symbol, state in open_state.items():
            if abs(state['qty']) > 1e-12:
                open_positions[symbol] = state['qty']
                direction = 1.0 if state['qty'] > 0 else -1.0
                gross = direction * (final_prices.get(symbol, 0.0) - state['avg_price']) \
                    * abs(state['qty'])
                _record_round_trip(
                    round_trip_ledger, common_index[-1],
                    symbol, direction, state['qty'], state['avg_price'],
                    final_prices.get(symbol, 0.0), gross, state['costs'],
                    'mark_to_market',
                )

        realized = [t for t in round_trip_ledger if t['kind'] == 'close']
        carried = [t for t in round_trip_ledger if t['kind'] == 'mark_to_market']

        # Convert equity curve to DataFrame
        equity_df = pd.DataFrame(equity_curve)
        equity_df.set_index('timestamp', inplace=True)
        
        # Calculate returns
        equity_df['returns'] = equity_df['equity'].pct_change().fillna(0)
        
        # Calculate performance metrics
        total_return = (final_equity - initial_capital) / initial_capital
        
        # Annualized return
        days = (equity_df.index[-1] - equity_df.index[0]).days
        if days > 0:
            annualized_return = (1 + total_return) ** (365 / days) - 1
        else:
            annualized_return = 0
            
        # Volatility (annualized)
        volatility = equity_df['returns'].std() * np.sqrt(252)  # Assuming daily data
        
        # Sharpe ratio (assuming 0% risk-free rate)
        sharpe_ratio = annualized_return / volatility if volatility > 0 else 0
        
        # Max drawdown
        rolling_max = equity_df['equity'].cummax()
        drawdown = (equity_df['equity'] - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        
        # Win rate over REALIZED round trips only, net of the costs charged to them.
        # (It used to count executions whose notional was > 0, which is every
        # execution, so it reported 100% on any book that traded at all.)
        nets = [t['net_pnl'] for t in realized]
        wins = [p for p in nets if p > 0]
        losses = [p for p in nets if p < 0]
        win_rate = len(wins) / len(nets) if nets else 0
        realized_gross = sum(t['gross_pnl'] for t in realized)
        realized_costs = sum(t['costs'] for t in realized)
        realized_net = sum(nets)
        unrealized_gross = sum(t['gross_pnl'] for t in carried)
        unrealized_costs = sum(t['costs'] for t in carried)
        unrealized_net = sum(t['net_pnl'] for t in carried)
        gross_pnl = realized_gross + unrealized_gross
        total_costs = realized_costs + unrealized_costs
        # A position carried to the last bar has not paid for its way out yet.
        exit_cost_on_open_positions = sum(
            abs(q) * final_prices.get(symbol, 0.0) for symbol, q in open_positions.items()
        ) * (commission + slippage)
        if losses:
            profit_factor = sum(wins) / abs(sum(losses))
        else:
            # Undefined, not infinite: a book with wins and no losses has no
            # denominator, and `inf` in a report reads as "unbounded edge".
            profit_factor = None if wins else 0.0

        cost_block = cost_sensitivity(
            gross_pnl=gross_pnl,
            costs=total_costs,
            commission=commission,
            slippage=slippage,
            unit_values=nets,
            exit_cost_on_open_positions=exit_cost_on_open_positions,
        )

        # Store results
        self.results = {
            'equity_curve': equity_df,
            'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
            'round_trips': (pd.DataFrame(round_trip_ledger) if round_trip_ledger
                            else pd.DataFrame(columns=[
                                'timestamp', 'symbol', 'direction', 'qty_closed',
                                'entry_price', 'exit_price', 'gross_pnl', 'costs',
                                'net_pnl', 'kind'])),
            'realized_round_trips': (pd.DataFrame(realized) if realized
                                     else pd.DataFrame(columns=[
                                         'timestamp', 'symbol', 'direction', 'qty_closed',
                                         'entry_price', 'exit_price', 'gross_pnl', 'costs',
                                         'net_pnl', 'kind'])),
            'positions': positions,
            'open_positions_at_end': open_positions,
            'final_equity': final_equity,
            'initial_capital': initial_capital,
            'total_return': total_return,
            'annualized_return': annualized_return,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'n_round_trips': len(nets),
            'winning_round_trips': len(wins),
            'losing_round_trips': len(losses),
            'n_mark_to_market': len(carried),
            'gross_pnl': gross_pnl,
            'net_pnl': realized_net + unrealized_net,
            'realized_gross_pnl': realized_gross,
            'realized_costs': realized_costs,
            'realized_net_pnl': realized_net,
            'unrealized_gross_pnl': unrealized_gross,
            'unrealized_costs': unrealized_costs,
            'unrealized_net_pnl': unrealized_net,
            'exit_cost_on_open_positions': exit_cost_on_open_positions,
            'net_pnl_if_flat_at_end': realized_net + unrealized_net - exit_cost_on_open_positions,
            'total_costs': total_costs,
            'profit_factor': profit_factor,
            'cost_sensitivity': cost_block,
            'commission': commission,
            'slippage': slippage,
            'total_trades': len(trades),
            'period_start': equity_df.index[0] if len(equity_df) > 0 else None,
            'period_end': equity_df.index[-1] if len(equity_df) > 0 else None
        }
        
        logger.info(f"Event-driven backtest completed. Final equity: ${final_equity:,.2f}")
        return self.results
    
    def _get_common_index(self, data: Dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
        """Get common time index across all symbols"""
        if not data:
            return pd.DatetimeIndex([])
        
        # Start with first symbol's index
        common_index = set(data[list(data.keys())[0]].index)
        
        # Intersect with all other symbols
        for symbol, df in data.items():
            common_index = common_index.intersection(set(df.index))
        
        return pd.DatetimeIndex(sorted(list(common_index)))
    
    def get_results(self) -> Dict:
        """Get backtest results"""
        return self.results
    
    def get_tear_sheet(self) -> str:
        """Generate a tear sheet of backtest performance"""
        if not self.results:
            return "No results available. Run backtest first."
        
        r = self.results
        cs = r.get('cost_sensitivity') or {}
        n = r['n_round_trips']
        n_marks = r.get('n_mark_to_market', len(r['open_positions_at_end']))
        sig = cs.get('significance') or {}
        pf = r['profit_factor']
        pf_display = 'undefined (wins, no losing round trip)' if pf is None else f'{pf:.2f}'
        be = cs.get('break_even_bps_per_side')
        be_display = f"{be:.1f} bps/side" if be is not None else 'no fee clears this book'
        scenario_lines = '\n'.join(
            f"  {s['fee_bps_per_side']:>5.1f} bps/side ({s['label']}): "
            f"net ${s['net_pnl']:,.2f} {'clears' if s['clears'] else 'DOES NOT CLEAR'}"
            for s in cs.get('scenarios', [])
        )
        tear_sheet = f"""
BACKTEST TEAR SHEET
===================
Period: {r['period_start'].strftime('%Y-%m-%d') if r['period_start'] else 'N/A'} to {r['period_end'].strftime('%Y-%m-%d') if r['period_end'] else 'N/A'}
Initial Capital: ${r['initial_capital']:,.2f}
Final Equity: ${r['final_equity']:,.2f}

RETURNS
-------
Total Return: {r['total_return']:.2%}
Annualized Return: {r['annualized_return']:.2%}
Volatility: {r['volatility']:.2%}
Sharpe Ratio: {r['sharpe_ratio']:.2f}

RISK METRICS
------------
Max Drawdown: {r['max_drawdown']:.2%}
Win Rate: {r['win_rate']:.2%} ({n} realized round trips)
Total Trades: {r['total_trades']}

REALIZED ROUND TRIPS (closed by a fill, net of their costs)
-----------------------------------------------------------
Wins: {r['winning_round_trips']}, losses: {r['losing_round_trips']}
Gross P&L: ${r['realized_gross_pnl']:,.2f}
Costs paid: ${r['realized_costs']:,.2f}
Net P&L: ${r['realized_net_pnl']:,.2f}
Profit factor: {pf_display}

POSITIONS CARRIED TO THE LAST BAR (marked, NOT realized)
--------------------------------------------------------
{n_marks} marked, excluded from Win Rate / Profit factor above
Gross mark: ${r['unrealized_gross_pnl']:,.2f}  (costs already accrued: ${r['unrealized_costs']:,.2f})
Exit fee still unpaid on them: ${cs.get('exit_cost_on_open_positions', 0.0):,.2f}

COST SENSITIVITY (net of fees, not gross)
-----------------------------------------
Modelled: commission {r['commission']:.2%} + slippage {r['slippage']:.2%} per fill
= {cs.get('modelled_cost_bps_per_round_trip', 0):.1f} bps per round trip, so a round trip needs
{cs.get('min_gross_bps_per_round_trip_to_break_even', 0):.1f} bps of gross edge just to pay for itself.
Break-even fee: {be_display}
{scenario_lines}

SIGNIFICANCE
------------
Mean net per realized round trip: {sig.get('mean') if sig.get('mean') is None else f"${sig['mean']:,.2f}"} over n={sig.get('n')}
95% CI: {sig.get('ci95_low') if sig.get('ci95_low') is None else f"${sig['ci95_low']:,.2f}"} to {sig.get('ci95_high') if sig.get('ci95_high') is None else f"${sig['ci95_high']:,.2f}"}
Sample floor for a claim: {sig.get('min_reliable_sample')} realized round trips (never lowered)
Tradeable claim allowed: {cs.get('tradeable_claim_allowed')}
Blocked by: {cs.get('claim_blockers') or 'nothing'}

COST ASSUMPTION
---------------
Venue assumed: {cs.get('venue', 'n/a')}
{cs.get('funding_note', '')}
Total ledger P&L (realized + marks): gross ${r['gross_pnl']:,.2f} - costs ${r['total_costs']:,.2f} = net ${r['net_pnl']:,.2f}
"""
        return tear_sheet.strip()


def run_event_driven_backtest(
    signals: Dict[str, pd.Series],
    data: Dict[str, pd.DataFrame],
    initial_capital: float = 100000,
    commission: float = 0.001,
    slippage: float = 0.0005
) -> Dict:
    """
    Convenience function to run event-driven backtest
    
    Args:
        signals: Dictionary of symbol -> signal series
        data: Dictionary of symbol -> OHLCV DataFrame
        initial_capital: Starting capital
        commission: Commission rate
        slippage: Slippage rate
        
    Returns:
        Dictionary containing backtest results
    """
    backtester = EventDrivenBacktester()
    return backtester.run_backtest(
        signals=signals,
        data=data,
        initial_capital=initial_capital,
        commission=commission,
        slippage=slippage
    )
