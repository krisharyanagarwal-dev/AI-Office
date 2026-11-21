"""OpenClaw Trader Execution Engine
Bridges OpenClaw agent market analysis with paper trading execution.

WARNING: This system operates under "PAPER ONLY" constraints per BRAIN.md.
No real orders, no trading API keys, no funds. Ever.
Paper trading simulation only. Use for strategy testing and analysis.
"""

import asyncio
import os
import re
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple

from alpha.data.stock_metrics import load_stock_metrics, symbol_fundamentals
from alpha.execution.execution_engine import (
    Order, OrderSide, OrderType, OrderStatus, TimeInForce,
    Fill, PaperBroker as BasePaperBroker
)
from trading.risk import RiskLimits, RiskGovernor, LimitStatus

logger = logging.getLogger(__name__)


class OpenClawSignalParser:
    """Parses market analysis text from OpenClaw trader agent
    and extracts actionable trade signals.
    """

    # Patterns for trade signals in analysis text
    PATTERNS = {
        'buy': [
            r'\b(?:buy|long|accumulate|build position|going long)\s+(?:in|on)?\s*(\w+)?(?:\s+at\s+[\$]?\d+(?:\.\d+)?(?:\d+))?',
            r'\b(?:buy|long)\s+(\d+(?:\.\d+)?)\s+(?:of\s+)?(\w+)?',
            r'(\w{2,10})\s*:?\s*(?:buy|long|target|\+\+|🚀)',
            r'(?:BTC|ETH|RELIANCE|INFY|AAPL|TSLA|TCS|SBIN|ICICIBANK)\s+(?:is|shows|expected|projected|set|target|looking|trend|momentum|strong|rise|gain|breaking|upward)',
        ],
        'sell': [
            r'\b(?:sell|short|exit|take profit|reduce position|taking profits)\s+(?:in|on)?\s*(\w+)?(?:\s+at\s+[\$]?\d+(?:\.\d+)?(?:\d+))?',
            r'\b(?:sell|short)\s+(\d+(?:\.\d+)?)\s+(?:of\s+)?(\w+)?',
            r'(\w{2,10})\s*:?\s*(?:sell|short|target|--\-|📉)',
            r'(?:BTC|ETH|RELIANCE|INFY|AAPL|TSLA|TCS|SBIN|ICICIBANK)\s+(?:down|drop|decline|bearish|decreasing|fall|loss|weak|breaking|downward)',
        ],
        'symbol': [
            r'\b(?:BTC|ETH|SPY|QQQ|AAPL|TSLA|RELIANCE|INFY)\b',
            r'\b(\w{2,10}-\USD|\w{1,5}\.\w*)\b',
        ]
    }

    # Whitelist of tickers the parser recognizes, used to resolve the symbol
    # actually referenced by a regex match rather than the loop variable.
    KNOWN_TICKERS = frozenset([
        'BTC', 'ETH', 'SOL', 'ADA', 'AVAX', 'MATIC', 'LINK', 'UNI', 'ATOM',
        'USDT', 'USDC',
        'RELIANCE', 'INFY', 'TCS', 'HDFCBANK', 'ICICIBANK', 'SBIN',
        'ITC', 'BHARTIARTL', 'TATAMOTOR', 'M&M', 'HCLTECH', 'WIPRO', 'ONGC',
        'COALINDIA', 'NTPC', 'POWERGRID',
        'AAPL', 'TSLA', 'SPY', 'QQQ', 'MSFT', 'GOOGL', 'AMZN', 'NVDA',
        'FB', 'BRK.B', 'JPM', 'JNJ', 'V', 'WMT', 'PG', 'MA',
    ])

    def __init__(self):
        self.last_analysis = ""
        self.last_signals = []

    def _resolve_symbol(self, match: re.Match, fallback: str) -> str:
        """Resolve the ticker actually referenced by a regex match.

        Pattern 4 matches a literal ticker (e.g. "BTC shows") but its groups
        don't capture it, so the leading token of the match is used. Group
        captures (pattern 3's symbol, pattern 1/2's optional symbol) take
        precedence when they resolve to a known ticker. Falls back to the
        iteration symbol when no ticker can be resolved from the match.
        """
        if match.lastindex:
            for i in range(1, match.lastindex + 1):
                group = match.group(i)
                if group and group.upper() in self.KNOWN_TICKERS:
                    return group.upper()
        leading = match.group(0).split()[0].upper()
        if leading in self.KNOWN_TICKERS:
            return leading
        return fallback

    def parse(self, analysis_text: str) -> List[Dict[str, Any]]:
        """Parse OpenClaw analysis text for trade signals.

        Returns list of signal dicts with symbol, side, confidence, etc.
        Dedups by (symbol, side) to prevent double-exposure from
        line-level matches + overall-sentiment fallback.
        """
        self.last_analysis = analysis_text
        signals = []

        text_lower = analysis_text.lower()

        # Extract symbols mentioned
        symbols = self._extract_symbols(analysis_text)

        # Extract buy/sell intent
        for line in analysis_text.split('\n'):
            line_lower = line.lower().strip()
            if not line_lower:
                continue

            signal = self._analyze_line(line_lower, symbols)
            if signal:
                signals.append(signal)

        # Deduplicate all signals by (symbol, side), keeping the first occurrence
        # This prevents double-exposure from line-level matches + overall-sentiment fallback
        seen = set()
        deduped = []
        for s in signals:
            key = (s.get('symbol'), s.get('side'))
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        signals = deduped

        # Also check for overall sentiment (will be naturally deduped if a line signal
        # with the same (symbol, side) already exists, due to the dedupe above)
        overall = self._analyze_overall_sentiment(text_lower, symbols)
        if overall:
            already = any(
                s.get('symbol') == overall.get('symbol') and s.get('side') == overall.get('side')
                for s in signals
            )
            if not already:
                signals.append(overall)

        self.last_signals = signals
        return signals

    def _extract_symbols(self, text: str) -> List[str]:
        """Extract cryptocurrency and stock symbols from text.

        Uses a whitelist approach: only recognized financial tickers are extracted.
        Business metrics (CAC, LTV, RTO, etc.) are excluded.
        Uses word boundary matching to avoid substring matches within words.
        """
        symbols = set()

        text_lower = text.lower()
        text_upper = text.upper()

        # Known cryptocurrency tickers - check with word boundary
        crypto_tickers = ['BTC', 'ETH', 'SOL', 'ADA', 'AVAX', 'MATIC', 'LINK', 'UNI', 'ATOM',
                          'USDT', 'USDC']

        for ticker in crypto_tickers:
            # Match ticker as whole word with word boundaries (case-insensitive since text_lower is lowercase)
            if re.search(r'\b' + ticker + r'\b', text_lower, re.IGNORECASE):
                symbols.add(ticker)

        # Known Indian equity tickers - check with word boundary
        indian_tickers = ['RELIANCE', 'INFY', 'TCS', 'HDFCBANK', 'ICICIBANK', 'SBIN',
                          'ITC', 'BHARTIARTL', 'TATAMOTOR', 'M&M', 'HCLTECH',
                          'WIPRO', 'ONGC', 'COALINDIA', 'NTPC', 'POWERGRID']

        for ticker in indian_tickers:
            # Use word boundary regex for exact match (case-insensitive)
            if re.search(r'\b' + re.escape(ticker) + r'\b', text_lower, re.IGNORECASE):
                symbols.add(ticker)

        # Known US equity tickers - check with word boundary
        us_tickers = ['AAPL', 'TSLA', 'SPY', 'QQQ', 'MSFT', 'GOOGL', 'AMZN', 'NVDA',
                      'FB', 'BRK.B', 'JPM', 'JNJ', 'V', 'WMT', 'PG', 'MA']

        for ticker in us_tickers:
            # Handle tickers with dots (BRK.B) - split on dot for matching
            ticker_variants = [ticker]
            if '.' in ticker:
                ticker_variants = [ticker.replace('.', '.'), ticker.replace('.', '')]
            for t in ticker_variants:
                if re.search(r'\b' + re.escape(t) + r'\b', text_lower, re.IGNORECASE):
                    symbols.add(ticker)
                    break

        return list(symbols)

    def _analyze_line(self, line: str, symbols: List[str]) -> Optional[Dict[str, Any]]:
        """Analyze a single line for trade signals."""
        for symbol in symbols:
            # Check for buy patterns
            for pattern in self.PATTERNS['buy']:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    resolved_symbol = self._resolve_symbol(match, symbol)
                    return {
                        'symbol': resolved_symbol,
                        'side': 'buy',
                        'confidence': 0.7,
                        'source_text': line.strip(),
                        'extracted': match.group(0),
                    }

            # Check for sell patterns
            for pattern in self.PATTERNS['sell']:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    resolved_symbol = self._resolve_symbol(match, symbol)
                    return {
                        'symbol': resolved_symbol,
                        'side': 'sell',
                        'confidence': 0.7,
                        'source_text': line.strip(),
                        'extracted': match.group(0),
                    }

        return None

    def _analyze_overall_sentiment(self, text: str, symbols: List[str]) -> Optional[Dict[str, Any]]:
        """Analyze overall bullish/bearish sentiment without specific signals."""
        if not symbols:
            return None

        bullish_words = ['bullish', 'rise', 'growth', 'profit', 'gain', 'positive', 'uptrend', 'momentum', 'breakout', 'gains']
        bearish_words = ['bearish', 'drop', 'loss', 'decline', 'negative', 'downtrend', 'risk', 'correction', 'drawdown']

        bullish_count = sum(1 for w in bullish_words if w in text)
        bearish_count = sum(1 for w in bearish_words if w in text)

        # If one side clearly dominates
        if bullish_count > bearish_count and symbols:
            confidence = min(0.9, 0.4 + (bullish_count - bearish_count) * 0.15)
            return {
                'symbol': symbols[0],
                'side': 'buy',
                'confidence': confidence,
                'source_text': 'overall sentiment analysis',
                'extracted': f'bullish_sentiment_{bullish_count}_{bearish_count}',
            }
        elif bearish_count > bullish_count and symbols:
            confidence = min(0.9, 0.4 + (bearish_count - bullish_count) * 0.15)
            return {
                'symbol': symbols[0],
                'side': 'sell',
                'confidence': confidence,
                'source_text': 'overall sentiment analysis',
                'extracted': f'bearish_sentiment_{bullish_count}_{bearish_count}',
            }

        # If sentiment is mixed or neutral but symbols mentioned, still return a signal
        # with lower confidence to prompt manual review
        if symbols and (bullish_count + bearish_count) > 0:
            # Equal or very close counts = mixed sentiment, prompt review
            if bullish_count == bearish_count:
                return {
                    'symbol': symbols[0],
                    'side': 'buy',
                    'confidence': 0.3,
                    'source_text': 'mixed/neutral sentiment - manual review recommended',
                    'extracted': f'mixed_sentiment_{bullish_count}_{bearish_count}',
                }

        return None


class OpenClawExecutionEngine:
    """Execution engine that takes OpenClaw trader agent analysis
    and executes paper trades accordingly.
    """

    def __init__(self,
                 initial_balance: float = 100000.0,
                 auto_execute: bool = False,
                 signal_parser: OpenClawSignalParser = None,
                 paper_broker: BasePaperBroker = None):
        """Initialize the execution engine.

        Args:
            initial_balance: Starting USDT balance for paper trading
            auto_execute: If True, auto-execute parsed signals (use with caution)
            signal_parser: OpenClawSignalParser for analysis parsing
            paper_broker: PaperBroker instance from alpha infrastructure
        """
        self.auto_execute = auto_execute
        self.signal_parser = signal_parser or OpenClawSignalParser()
        self.paper_broker = paper_broker or BasePaperBroker(initial_balance)
        self.execution_history: List[Dict] = []
        self.positions: Dict[str, Dict[str, float]] = {}

        # Risk governor — wired with locked default limits
        self.risk_limits = RiskLimits()
        self.risk_governor = RiskGovernor(self.risk_limits)
        self.risk_governor.update_start_of_day_equity(initial_balance)

        logger.info("OpenClaw Execution Engine initialized (PAPER ONLY mode)")

    def _attach_fundamentals(self, signals: List[Dict[str, Any]]) -> None:
        """Attach published fundamental facts to each parsed signal.

        Read-only context: the facts never change a signal's side or
        confidence, and a missing metrics file leaves the signals untouched.
        """
        try:
            metrics = load_stock_metrics()
        except Exception as e:  # noqa: BLE001 - context must never block execution
            logger.debug(f"fundamentals unavailable: {e}")
            return
        if not metrics:
            return
        for signal in signals:
            try:
                entry = symbol_fundamentals(metrics, signal.get("symbol", ""))
            except Exception as e:  # noqa: BLE001
                logger.debug(f"fundamentals lookup failed: {e}")
                continue
            if entry:
                signal["fundamentals"] = entry

    async def process_analysis(self, analysis_text: str) -> Dict[str, Any]:
        """Process OpenClaw trader agent analysis and execute trades.

        Args:
            analysis_text: Market analysis text from OpenClaw trader agent

        Returns:
            Dict with execution results and signals found
        """
        # Parse signals from analysis
        signals = self.signal_parser.parse(analysis_text)
        self._attach_fundamentals(signals)

        results = {
            'analysis_text': analysis_text[:200] + "..." if len(analysis_text) > 200 else analysis_text,
            'signals_found': len(signals),
            'signals': signals,
            'orders_executed': 0,
            'orders_rejected': 0,
            'pending_review': 0,
            'execution_details': [],
        }

        # Process each signal
        for signal in signals:
            try:
                # Respect auto_execute flag: manual review mode skips execution
                if not self.auto_execute:
                    # Mark signal as pending review without executing
                    resolved_symbol = signal.get('symbol', 'UNKNOWN')
                    resolved_side = signal.get('side', 'buy')
                    confidence = signal.get('confidence', 0.7)
                    results['execution_details'].append({
                        'signal': signal,
                        'status': 'pending_review',
                        'symbol': resolved_symbol,
                        'side': resolved_side,
                        'confidence': confidence,
                        'note': 'Manual review mode - signal not executed',
                    })
                    results['pending_review'] += 1
                    continue

                # Pre-trade risk check (auto-execute path only)
                symbol = signal.get('symbol', 'UNKNOWN')
                side = signal.get('side', 'buy')
                confidence = signal.get('confidence', 0.7)
                balance = self.paper_broker.balances.get('USDT', 0) or 100000.0
                notional_value = balance * 0.02  # 2% of balance as notional (will be recalculated in _execute_signal, but we check here with estimated)

                risk_status, risk_reason = self.risk_governor.check_all(
                    confidence, symbol, notional_value, balance
                )
                if risk_status != LimitStatus.PASS:
                    results['execution_details'].append({
                        'signal': signal,
                        'status': 'risk_rejected',
                        'reason': risk_reason,
                        'symbol': symbol,
                        'side': side,
                        'confidence': confidence,
                    })
                    results['orders_risk_rejected'] += 1
                    continue

                order_result = await self._execute_signal(signal, self.paper_broker)
                # Normalize status to plain string for consistent downstream consumption
                # OrderStatus is already imported from the PaperBroker module
                if isinstance(order_result.get('status'), OrderStatus):
                    order_result['status'] = order_result['status'].value
                results['execution_details'].append(order_result)

                status = order_result.get('status', '')
                if status in ('filled', 'partially_filled'):
                    results['orders_executed'] += 1
                elif status == 'rejected':
                    results['orders_rejected'] += 1
            except Exception as e:
                logger.error(f"Error executing signal: {e}")
                results['execution_details'].append({
                    'signal': signal,
                    'status': 'error',
                    'error': str(e),
                })

        # Record paper broker state in execution history
        self.execution_history.append({
            'timestamp': datetime.now(timezone.utc).timestamp(),
            'analysis_signals': len(signals),
            'orders_executed': results['orders_executed'],
            'orders_rejected': results['orders_rejected'],
            'symbols': [s.get('symbol') for s in signals],
            'broker_balance': self.paper_broker.balances.get('USDT', 0),
        })

        return results

    async def _execute_signal(self, signal: Dict[str, Any], paper_broker: BasePaperBroker) -> Dict[str, Any]:
        """Execute a single trade signal.

        Uses the PaperBroker for execution when auto_execute=True,
        otherwise simulates execution paper-trade style.
        """
        symbol = signal.get('symbol')
        side = signal.get('side')
        confidence = signal.get('confidence', 0.5)

        if not symbol or not side:
            return {'status': 'invalid', 'reason': 'missing symbol or side'}

        # Set market data first so quantity calculation uses correct prices
        if self.auto_execute:
            # Set market prices for known symbols before calculating quantity
            price_map = {
                'BTC': 67000.0,
                'ETH': 3500.0,
                'SPY': 500.0,
                'RELIANCE': 2800.0,
                'INFY': 1400.0,
                'AAPL': 180.0,
                'TSLA': 250.0,
            }
            for sym, price in price_map.items():
                paper_broker.set_market_data(sym, price)

        # Determine order quantity based on confidence AND available balance
        # Use a reasonable % of balance as notional value so orders don't get rejected
        balance = paper_broker.balances.get('USDT', 100000.0)
        notional_pct = 0.01  # 1% of balance per trade
        notional_value = balance * notional_pct  # USDT amount to trade
        # Get market price to convert to quantity
        market_price = paper_broker.get_market_price(symbol)
        if market_price and market_price > 0:
            qty = notional_value / market_price
        else:
            qty = notional_value / 1000.0  # fallback default price
        # Scale by confidence (higher confidence = larger position)
        qty = qty * confidence
        # Ensure minimum and maximum bounds
        qty = max(0.001, min(qty, 10.0))  # between 0.001 and 10 units

        # Create order
        order = Order(
            symbol=symbol,
            side=OrderSide.BUY if side == 'buy' else OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=qty,
            metadata={
                'source': 'openclaw_analysis',
                'confidence': confidence,
                'signal_text': signal.get('source_text', ''),
            }
        )

        # Execute via PaperBroker if auto_execute, otherwise simulate
        if self.auto_execute:
            order_result = await paper_broker.submit_order(order)
            # Normalize to dict for consistent return type
            if hasattr(order_result, 'status'):
                result = {
                    'status': order_result.status,
                    'order': order_result,
                    'fill': None,
                    'execution_price': getattr(order_result, 'filled_avg_price', 0.0),
                }
            else:
                result = order_result
        else:
            result = await self._simulate_execution(order, confidence, paper_broker)

        return result

    async def _simulate_execution(self, order: Order, confidence: float, paper_broker: BasePaperBroker) -> Dict[str, Any]:
        """Simulate order execution for paper trading.

        Gets current market price from PaperBroker and simulates execution
        with slippage based on confidence. Updates internal balances and positions.
        """
        # Get current market price from PaperBroker
        market_price = paper_broker.get_market_price(order.symbol)
        if market_price is None:
            # Use defaults based on symbol if not set
            price_map = {
                'BTC': 67000.0,
                'ETH': 3500.0,
                'SPY': 500.0,
                'RELIANCE': 2800.0,
                'INFY': 1400.0,
            }
            market_price = price_map.get(order.symbol, 100.0)

        # Apply simulated slippage based on confidence
        # Higher confidence = less slippage
        # Direction: buys fill worse than market, sells better — realistic execution
        slippage_pct = (1.0 - confidence) * 0.5  # Max 0.5% slippage
        if order.side == OrderSide.BUY:
            execution_price = market_price * (1 + slippage_pct)
        else:
            execution_price = market_price * (1 - slippage_pct)

        # Calculate commission
        commission = order.quantity * execution_price * 0.001  # 0.1% commission

        # Use PaperBroker's internal fill mechanism to update balances correctly
        # Create a fill and process it through the broker
        fill = Fill(
            order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=execution_price,
            commission=commission,
            timestamp=datetime.now(timezone.utc).timestamp(),
            exchange_fill_id=f"paper_{order.client_order_id}",
            liquidity="maker",
        )

        # Process the fill through PaperBroker's position/balance management
        await paper_broker._process_fill(fill)

        # Update our internal position tracking from the broker's state
        self._sync_positions_from_broker()

        return {
            'status': 'filled',
            'order': order,
            'fill': fill,
            'execution_price': execution_price,
            'slippage_pct': slippage_pct * 100,
        }

    async def submit_order_direct(self, symbol: str, side: str, quantity: float,
                                order_type: OrderType = OrderType.MARKET,
                                price: float = None) -> Dict[str, Any]:
        """Submit a trade order directly (bypassing analysis parsing).

        Useful for manual signal entry or testing.
        Uses PaperBroker for execution with paper-trade simulation.
        """
        # Create order
        order = Order(
            symbol=symbol,
            side=OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL,
            order_type=order_type,
            quantity=quantity,
            price=price,
            metadata={'source': 'direct_entry'}
        )

        # Execute via PaperBroker
        order_result = await self.paper_broker.submit_order(order)

        # Update our position tracking from the broker's state
        # The PaperBroker's _process_fill should have updated positions
        # Sync our positions dict with the broker's positions
        self._sync_positions_from_broker()

        # Normalize to a dict so callers can use .get() consistently
        if order_result.status == OrderStatus.FILLED:
            fill = next(
                (f for f in reversed(self.paper_broker.fills)
                 if f.order_id == order.client_order_id),
                None,
            )
            return {
                'status': order_result.status.value,
                'order': order_result,
                'fill': fill,
                'execution_price': (
                    order_result.avg_fill_price
                    if order_result.status == OrderStatus.FILLED else 0.0
                ),
            }
        else:
            return {
                'status': order_result.status.value,
                'order': order_result,
                'fill': None,
                'execution_price': 0.0,
            }

    def _sync_positions_from_broker(self):
        """Sync positions from PaperBroker after execution.
        
        Handles the case where PaperBroker's _process_fill updates
        positions differently than our tracking.
        """
        # PaperBroker tracks positions in self.positions dict
        # Our self.positions is independent; sync the quantities
        for symbol, broker_pos in self.paper_broker.positions.items():
            if symbol in self.positions:
                # Update our tracking with broker's state
                self.positions[symbol]['quantity'] = broker_pos.quantity
                self.positions[symbol]['avg_entry_price'] = broker_pos.avg_entry_price
                self.positions[symbol]['realized_pnl'] = broker_pos.realized_pnl
                self.positions[symbol]['unrealized_pnl'] = broker_pos.unrealized_pnl
            else:
                # Add new position from broker
                self.positions[symbol] = {
                    'quantity': broker_pos.quantity,
                    'avg_entry_price': broker_pos.avg_entry_price,
                    'realized_pnl': broker_pos.realized_pnl,
                    'unrealized_pnl': broker_pos.unrealized_pnl,
                }

    def get_status(self) -> Dict[str, Any]:
        """Get current engine status."""
        return {
            'pending_orders': len(self.pending_orders) if hasattr(self, 'pending_orders') else 0,
            'execution_history_count': len(self.execution_history),
            'balances': self.paper_broker.balances,
            'positions': {sym: {k: v for k, v in pos.items() if k != 'updated_at'} for sym, pos in self.positions.items()},
            'last_analysis_signals': self.signal_parser.last_signals,
            'broker_status': self.paper_broker.get_status() if hasattr(self.paper_broker, 'get_status') else 'active',
        }

    async def process_trader_signals(self, signals_path: str = None) -> Dict[str, Any]:
        """Process trader signals from a JSONL file.

        Reads trader signals from the AlphaInsider signals JSONL file (or a
        custom path) and executes them as paper trades.

        Each signal should have:
        - symbol: ticker symbol (e.g., 'BTC', 'ETH', 'RELIANCE')
        - direction: 'LONG' or 'SHORT' (maps to buy/sell)
        - confidence: float 0-1 (optional, defaults to 0.7)

        Returns execution summary.
        """
        # Determine signals file path
        if signals_path is None:
            # Default to the fleet's alphainsider signals file
            default_paths = [
                '/Users/aryanagarwal/AI-Office/packages/_archive/all-files/jsonl/alphainsider_signals.jsonl',
                '/Users/aryanagarwal/AI-Office/packages/_archive/oa-strat/state/alphainsider_signals.jsonl',
                '/Users/aryanagarwal/AI-Office/packages/_archive/all-files/jsonl/alphainsider_signals.jsonl',
            ]
            signals_path = None
            for path in default_paths:
                import os
                if os.path.exists(path):
                    signals_path = path
                    break

        import os
        if signals_path is None or not os.path.exists(signals_path):
            return {
                'signals_found': 0,
                'orders_executed': 0,
                'orders_rejected': 0,
                'error': f'No trader signals file found. Tried: {default_paths}',
            }

        # Read and parse signals
        signals = []
        try:
            with open(signals_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        signal = json.loads(line)
                        signals.append(signal)
                    except json.JSONDecodeError:
                        logger.warning(f'Skipping malformed signal line: {line[:50]}...')
                        continue
        except Exception as e:
            return {
                'signals_found': 0,
                'orders_executed': 0,
                'orders_rejected': 0,
                'error': f'Error reading signals file: {str(e)}',
            }

        # Convert signals to analysis text and process
        total_executed = 0
        total_rejected = 0
        total_pending_review = 0
        processed_signals = []

        for signal in signals:
            # Extract direction and symbol
            direction = signal.get('direction', '').upper()
            
            # Extract symbol - handle both top-level and raw field
            raw = signal.get('raw', {})
            symbol = signal.get('symbol', raw.get('symbol', '')).upper()

            # Skip if direction is missing or symbol is UNKNOWN/resolved
            if not direction or symbol == 'UNKNOWN':
                logger.warning(f'Skipping signal with missing direction/UNKNOWN symbol: {signal.get("signal_id", "unknown")}')
                continue

            # Map direction to side
            side = 'buy' if direction in ('LONG', 'BUY') else 'sell'

            # Get confidence (default 0.7)
            confidence = signal.get('confidence', 0.7)

            # Generate analysis text
            analysis_text = f"{symbol} showing {direction.lower()} momentum"

            # Parse and process
            try:
                parsed_signals = self.signal_parser.parse(analysis_text)
                if not parsed_signals:
                    logger.warning(f'No signals parsed for: {analysis_text}')
                    continue

                # Process each parsed signal
                for parsed in parsed_signals:
                    p_side = parsed['side']
                    p_symbol = parsed['symbol']
                    p_confidence = parsed['confidence']

                    # Respect auto_execute flag
                    if not self.auto_execute:
                        # Manual review mode: signal parsed but not executed
                        # Count as pending review — NOT as executed
                        total_pending_review += 1
                        processed_signals.append({
                            'original_signal': signal.get('signal_id'),
                            'symbol': p_symbol,
                            'side': p_side,
                            'confidence': p_confidence,
                            'execution_status': 'pending_review',
                            'manual_review': True,
                        })
                        continue

                    # Execute signal
                    result = await self._execute_signal(
                        {'side': p_side, 'symbol': p_symbol, 'confidence': p_confidence},
                        self.paper_broker,
                    )

                    if result.get('status') in ('filled', 'partially_filled'):
                        total_executed += 1
                    else:
                        total_rejected += 1

                    processed_signals.append({
                        'original_signal': signal.get('signal_id'),
                        'symbol': p_symbol,
                        'side': p_side,
                        'confidence': p_confidence,
                        'execution_status': result.get('status'),
                    })

            except Exception as e:
                logger.error(f'Error processing signal {signal.get("signal_id", "unknown")}: {e}')
                total_rejected += 1

        # Return summary
        return {
            'signals_found': len(signals),
            'orders_executed': total_executed,
            'orders_rejected': total_rejected,
            'pending_review': total_pending_review if 'total_pending_review' in dir() else 0,
            'processed_signals': processed_signals,
            'signals_file': signals_path,
        }


# CLI interface for testing
async def main():
    """CLI demo: process OpenClaw analysis and execute paper trades."""
    import sys

    engine = OpenClawExecutionEngine(auto_execute=False)

    print("=== OpenClaw Execution Engine ===")
    print("Mode: PAPER ONLY (no real orders, no API keys, no funds)")
    print()

    # Example 1: Indian D2C brand analysis
    example1 = """Indian D2C is maturing from hyper-growth to profitability.
CAC is rising due to platform ad inflation, prompting brands to shift
toward organic and performance marketing efficiency. Retention is the
new growth lever; brands are investing in subscription models and
loyalty programs to boost LTV. COD remains dominant (~60% of orders)
but prepaid conversion is improving as trust digitalizes, lowering
RTO rates. RTO remains a critical cost center, with brands leveraging
size charts and AI fit-technology to mitigate losses. Regulatory risks
center on data privacy, while logistics efficiency is the primary
differentiator. Seasonality drives volatility, requiring agile inventory management."""

    print("--- Example 1: Indian D2C Analysis ---")
    result = await engine.process_analysis(example1)
    print(f"Signals found: {result['signals_found']}")
    for signal in result['signals']:
        print(f"  - {signal['side']} {signal['symbol']} (conf: {signal['confidence']:.2f})")
    print(f"Orders executed: {result['orders_executed']}")
    print(f"Orders rejected: {result['orders_rejected']}")
    status = engine.get_status()
    print(f"Engine status: {status}")
    print(f"Balances: {status['balances']}")
    print(f"Positions: {status['positions']}")
    print()

    # Example 2: Crypto market analysis
    example2 = """BTC shows bullish momentum breaking above key resistance at
$67K. ETH following with strong volume confirmation. Risk-on sentiment
persists across crypto markets. Allin leg recommended for BTC/USD
entry around current levels with tight stop. Coinflip control
maintaining negative expected value - monitor for exit signals."""

    print("--- Example 2: Crypto Market Analysis ---")
    result = await engine.process_analysis(example2)
    print(f"Signals found: {result['signals_found']}")
    for signal in result['signals']:
        print(f"  - {signal['side']} {signal['symbol']} (conf: {signal['confidence']:.2f})")
    print(f"Orders executed: {result['orders_executed']}")
    print(f"Orders rejected: {result['orders_rejected']}")
    status = engine.get_status()
    print(f"Engine status: {status}")
    print(f"Balances: {status['balances']}")
    print(f"Positions: {status['positions']}")
    print()

    # Example 3: Direct order submission
    print("--- Example 3: Direct Order ---")
    result = await engine.submit_order_direct('BTC', 'buy', 0.1, price=67000.0)
    print(f"Order status: {result.get('status')}")
    fill = result.get('fill')
    if fill:
        print(f"Fill price: ${fill.price:,.2f}")
        print(f"Fill qty: {fill.quantity} BTC")
        print(f"Commission: ${fill.commission:.2f}")
    status = engine.get_status()
    print(f"Balances after direct order: {status['balances']}")
    print(f"Positions after direct order: {status['positions']}")
    print()

    print("=== Execution Engine Summary ===")
    print("All operations are paper/trade-simulation only.")
    print("No real orders, no API keys, no funds. Ever.")


if __name__ == "__main__":
    asyncio.run(main())