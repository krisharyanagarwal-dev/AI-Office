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
            commission: Commission rate (default: 0.1%)
            slippage: Slippage rate (default: 0.05%)
            
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
        
        # Win rate from trades
        profitable_trades = [t for t in trades if t['value'] > 0]  # Simplified
        win_rate = len(profitable_trades) / len(trades) if trades else 0
        
        # Store results
        self.results = {
            'equity_curve': equity_df,
            'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
            'positions': positions,
            'final_equity': final_equity,
            'initial_capital': initial_capital,
            'total_return': total_return,
            'annualized_return': annualized_return,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
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
Win Rate: {r['win_rate']:.2%}
Total Trades: {r['total_trades']}
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
