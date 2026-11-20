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
            config_path: Path to configuration file (default: config/settings.yaml relative to package)
        """
        if config_path is None:
            # Find config relative to this file's location
            # File is at: trading/alpha/backtest/vectorized.py
            # Want: trading/config/settings.yaml
            base = Path(__file__).resolve().parents[2]  # trading/alpha -> trading/
            config_path = base / "config" / "settings.yaml"
        self.config_path = str(config_path)
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
        pnl_after_costs = self._apply_transaction_costs(
            pnl, positions, data, 
            commission=self.config.get('backtest', {}).get('costs', {}).get('commission', 0.0005),
            slippage=self.config.get('backtest', {}).get('costs', {}).get('slippage', 0.0003),
            spread=self.config.get('backtest', {}).get('costs', {}).get('spread', 0.0002)
        )
        
        # Calculate equity curve
        equity_curve = self._calculate_equity_curve(pnl_after_costs, initial_capital)
        
        # Calculate performance metrics
        metrics = self._calculate_metrics(equity_curve, returns, positions)
        
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
            'initial_capital': initial_capital,
            'config': self.config
        }
        
        return self.results

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
                                spread: float = 0.0002) -> Dict[str, pd.Series]:
        """Apply transaction costs to P&L"""
        pnl_after_costs = {}
        
        for symbol in pnl.keys():
            if symbol in positions and symbol in data:
                # Calculate turnover (absolute change in position)
                turnover = positions[symbol].diff().abs().fillna(0)
                
                # Calculate costs
                # Commission: flat rate per trade
                commission_cost = turnover * commission
                
                # Slippage: depends on volume and volatility
                # Simplified: fixed percentage of turnover
                slippage_cost = turnover * slippage
                
                # Spread: paid on entry and exit
                # Simplified: half spread per trade
                spread_cost = turnover * spread
                
                total_costs = commission_cost + slippage_cost + spread_cost
                
                # Subtract costs from P&L
                pnl_after_costs[symbol] = pnl[symbol] - total_costs
            else:
                pnl_after_costs[symbol] = pnl[symbol]
                
        return pnl_after_costs
    
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
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
        
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
        
        tear_sheet = f"""
BACKTEST TEAR SHEET
===================
Period: {self.results['equity_curve'].index[0].date()} to {self.results['equity_curve'].index[-1].date()}
Initial Capital: ${self.results.get('initial_capital', 0):,.2f}
Final Equity: ${self.results['equity_curve'].iloc[-1]:,.2f}

RETURNS
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
Win Rate: {metrics.get('win_rate', 0):.2%}
Profit Factor: {metrics.get('profit_factor', 0):.2f}

TRADE STATISTICS
----------------
Total Days: {metrics.get('total_days', 0)}
Winning Days: {metrics.get('winning_days', 0)}
Losing Days: {metrics.get('total_days', 0) - metrics.get('winning_days', 0)}
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