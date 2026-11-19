"""
WebSocket Data Providers for Real-time Market Data
Supports Binance, Bybit, and other exchanges
"""
import asyncio
import json
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from collections import defaultdict
from datetime import datetime
import websockets
import orjson
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class Bar:
    """Immutable OHLCV bar"""
    symbol: str
    timestamp: int  # milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int = 0
    quote_volume: float = 0.0


@dataclass
class OrderBookSnapshot:
    """Order book snapshot"""
    symbol: str
    timestamp: int
    bids: List[tuple]  # [(price, size), ...]
    asks: List[tuple]


class BaseWSProvider(ABC):
    """Abstract base class for WebSocket providers"""
    
    def __init__(
        self,
        symbols: List[str],
        on_bar: Callable[[Bar], None],
        on_orderbook: Optional[Callable[[OrderBookSnapshot], None]] = None,
        on_trade: Optional[Callable[[dict], None]] = None,
        max_reconnect_attempts: int = 0,
        reconnect_base_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
        ping_interval: int = 20,
        ping_timeout: int = 10,
        health_check_interval: float = 30.0,
        stale_threshold: float = 120.0,
    ):
        self.symbols = symbols
        self.on_bar = on_bar
        self.on_orderbook = on_orderbook
        self.on_trade = on_trade
        # max_reconnect_attempts = 0 means unlimited (24/7 operation)
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_base_delay = reconnect_base_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.health_check_interval = health_check_interval
        self.stale_threshold = stale_threshold
        
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_count = 0
        self._last_message_time = 0
        self._tasks: List[asyncio.Task] = []
        
        # Bar aggregation buffers
        self._bar_buffers: Dict[str, Dict] = defaultdict(lambda: {
            'open': None, 'high': None, 'low': None, 'close': None,
            'volume': 0.0, 'trades': 0, 'start_ts': 0
        })
        
        # Orderbook cache
        self._orderbooks: Dict[str, Dict] = {}
        
    @property
    @abstractmethod
    def ws_url(self) -> str:
        """WebSocket endpoint URL"""
        pass
    
    @abstractmethod
    def _build_subscribe_message(self, symbols: List[str]) -> dict:
        """Build subscription message"""
        pass
    
    @abstractmethod
    def _parse_message(self, msg: dict) -> Optional[List[Any]]:
        """Parse incoming message, return list of events"""
        pass
    
    async def connect(self):
        """Establish WebSocket connection with indefinite auto-reconnect (24/7).

        The reconnect loop runs forever while self._running is True.
        Set max_reconnect_attempts = 0 (default) for unlimited reconnects.
        """
        self._running = True
        self._reconnect_count = 0

        while self._running:
            try:
                logger.info(f"Connecting to {self.ws_url}")
                self._ws = await websockets.connect(
                    self.ws_url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    max_size=10_000_000,
                )

                # Subscribe to streams
                sub_msg = self._build_subscribe_message(self.symbols)
                await self._ws.send(orjson.dumps(sub_msg).decode())
                logger.info(f"Subscribed to {len(self.symbols)} symbols")

                self._reconnect_count = 0
                await self._listen()

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Connection closed: {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Connection error: {e}")

            if self._running:
                await self._reconnect()
    
    async def _listen(self):
        """Listen for incoming messages"""
        try:
            async for msg in self._ws:
                self._last_message_time = time.time()
                try:
                    data = orjson.loads(msg)
                    events = self._parse_message(data)
                    if events:
                        for event in events:
                            await self._handle_event(event)
                except orjson.JSONDecodeError:
                    logger.warning("Failed to decode message")
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
        except websockets.exceptions.ConnectionClosed:
            raise
        except Exception as e:
            logger.error(f"Listen error: {e}")
            raise
    
    @abstractmethod
    async def _handle_event(self, event: Any):
        """Handle parsed event"""
        pass
    
    async def _reconnect(self):
        """Reconnect with exponential backoff.

        If max_reconnect_attempts = 0 (default), reconnects indefinitely
        for 24/7 operation. Otherwise stops after the configured limit.
        """
        self._reconnect_count += 1

        # Circuit breaker: honor explicit attempt limit (0 = unlimited)
        if self.max_reconnect_attempts > 0 and self._reconnect_count > self.max_reconnect_attempts:
            logger.error(
                f"Max reconnect attempts ({self.max_reconnect_attempts}) reached, giving up"
            )
            self._running = False
            return

        delay = min(
            self.reconnect_base_delay * (2 ** (self._reconnect_count - 1)),
            self.max_reconnect_delay,
        )
        logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_count})")
        await asyncio.sleep(delay)
    
    async def stop(self):
        """Stop the provider"""
        self._running = False
        if self._ws:
            await self._ws.close()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
    
    def get_last_message_age(self) -> float:
        """Get seconds since last message"""
        if self._last_message_time == 0:
            return float('inf')
        return time.time() - self._last_message_time
    
    def is_healthy(self) -> bool:
        """Check if connection is healthy"""
        return self._running and self.get_last_message_age() < 60

    def get_status(self) -> dict:
        """Get detailed provider status for monitoring"""
        return {
            "provider": type(self).__name__,
            "running": self._running,
            "connected": self._ws is not None and self.is_healthy(),
            "reconnect_count": self._reconnect_count,
            "last_message_age": self.get_last_message_age(),
            "symbols": self.symbols,
        }

    async def supervise(self):
        """Supervise connection health and force reconnect on stale connection (24/7).

        Runs until self._running is False. If no message has been received for
        stale_threshold seconds, closes the WebSocket to trigger a reconnect.
        """
        while self._running:
            try:
                await asyncio.sleep(self.health_check_interval)
                if not self._running:
                    break

                age = self.get_last_message_age()
                if age > self.stale_threshold and self._ws:
                    logger.warning(
                        f"Connection stale ({age:.0f}s since last message), forcing reconnect"
                    )
                    await self._ws.close()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Supervision error: {e}")


class BinanceWSProvider(BaseWSProvider):
    """Binance WebSocket Provider for Spot and Futures"""
    
    def __init__(
        self,
        symbols: List[str],
        on_bar: Callable[[Bar], None],
        on_orderbook: Optional[Callable[[OrderBookSnapshot], None]] = None,
        on_trade: Optional[Callable[[dict], None]] = None,
        futures: bool = False,
        testnet: bool = False,
        **kwargs
    ):
        self.futures = futures
        self.testnet = testnet
        super().__init__(symbols, on_bar, on_orderbook, on_trade, **kwargs)
        
        # Bar aggregation: 1-minute bars
        self._bar_interval_ms = 60_000
        
        # Track subscribed streams
        self._streams: List[str] = []
    
    @property
    def ws_url(self) -> str:
        if self.testnet:
            return "wss://stream.binancefuture.com/stream" if self.futures else "wss://testnet.binance.vision/stream"
        return "wss://fstream.binance.com/stream" if self.futures else "wss://stream.binance.com/stream"
    
    def _build_subscribe_message(self, symbols: List[str]) -> dict:
        streams = []
        for sym in symbols:
            sym_lower = sym.lower()
            # Trade streams for bar building
            streams.append(f"{sym_lower}@trade")
            # Kline streams for 1m bars
            streams.append(f"{sym_lower}@kline_1m")
            # Depth streams for orderbook
            streams.append(f"{sym_lower}@depth@100ms")
        
        self._streams = streams
        return {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": int(time.time() * 1000)
        }
    
    def _parse_message(self, msg: dict) -> Optional[List[Any]]:
        if "stream" not in msg or "data" not in msg:
            return None
        
        stream = msg["stream"]
        data = msg["data"]
        
        if "@trade" in stream:
            return [{"type": "trade", "symbol": data["s"], "data": data}]
        elif "@kline" in stream:
            kline = data["k"]
            if kline["x"]:  # Closed kline
                return [{"type": "kline", "symbol": kline["s"], "data": kline}]
        elif "@depth" in stream:
            return [{"type": "depth", "symbol": data["s"], "data": data}]
        
        return None
    
    async def _handle_event(self, event: dict):
        ev_type = event["type"]
        symbol = event["symbol"]
        data = event["data"]
        
        if ev_type == "trade":
            await self._process_trade(symbol, data)
        elif ev_type == "kline":
            await self._process_kline(symbol, data)
        elif ev_type == "depth":
            await self._process_depth(symbol, data)
    
    async def _process_trade(self, symbol: str, data: dict):
        """Process trade for real-time bar updates"""
        price = float(data["p"])
        qty = float(data["q"])
        timestamp = data["T"]
        is_buyer_maker = data["m"]
        
        buf = self._bar_buffers[symbol]
        interval_start = (timestamp // self._bar_interval_ms) * self._bar_interval_ms
        
        if buf['start_ts'] != interval_start:
            # Emit completed bar
            if buf['open'] is not None:
                await self._emit_bar(symbol, buf)
            # Start new bar
            buf.update({
                'open': price, 'high': price, 'low': price, 'close': price,
                'volume': qty, 'trades': 1, 'start_ts': interval_start
            })
        else:
            buf['high'] = max(buf['high'], price)
            buf['low'] = min(buf['low'], price)
            buf['close'] = price
            buf['volume'] += qty
            buf['trades'] += 1
        
        if self.on_trade:
            self.on_trade({
                'symbol': symbol,
                'price': price,
                'qty': qty,
                'timestamp': timestamp,
                'is_buyer_maker': is_buyer_maker
            })
    
    async def _process_kline(self, symbol: str, kline: dict):
        """Process closed kline for official 1m bars"""
        bar = Bar(
            symbol=symbol,
            timestamp=kline["t"],
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            trades=kline["n"],
            quote_volume=float(kline["q"])
        )
        if self.on_bar:
            self.on_bar(bar)
    
    async def _process_depth(self, symbol: str, data: dict):
        """Process orderbook depth update"""
        if self.on_orderbook:
            snapshot = OrderBookSnapshot(
                symbol=symbol,
                timestamp=data["E"],
                bids=[(float(p), float(q)) for p, q in data["b"]],
                asks=[(float(p), float(q)) for p, q in data["a"]]
            )
            self.on_orderbook(snapshot)
    
    async def _emit_bar(self, symbol: str, buf: dict):
        bar = Bar(
            symbol=symbol,
            timestamp=buf['start_ts'],
            open=buf['open'],
            high=buf['high'],
            low=buf['low'],
            close=buf['close'],
            volume=buf['volume'],
            trades=buf['trades']
        )
        if self.on_bar:
            self.on_bar(bar)


class BybitWSProvider(BaseWSProvider):
    """Bybit WebSocket Provider (V5 API)"""
    
    def __init__(
        self,
        symbols: List[str],
        on_bar: Callable[[Bar], None],
        on_orderbook: Optional[Callable[[OrderBookSnapshot], None]] = None,
        on_trade: Optional[Callable[[dict], None]] = None,
        testnet: bool = False,
        **kwargs
    ):
        self.testnet = testnet
        super().__init__(symbols, on_bar, on_orderbook, on_trade, **kwargs)
        self._bar_interval_ms = 60_000
    
    @property
    def ws_url(self) -> str:
        if self.testnet:
            return "wss://stream-testnet.bybit.com/v5/public/linear"
        return "wss://stream.bybit.com/v5/public/linear"
    
    def _build_subscribe_message(self, symbols: List[str]) -> dict:
        topics = []
        for sym in symbols:
            topics.append(f"publicTrade.{sym}")
            topics.append(f"kline.1.{sym}")
            topics.append(f"orderbook.1.{sym}")
        
        return {
            "op": "subscribe",
            "args": topics,
            "req_id": f"sub_{int(time.time() * 1000)}"
        }
    
    def _parse_message(self, msg: dict) -> Optional[List[Any]]:
        if "topic" not in msg or "data" not in msg:
            return None
        
        topic = msg["topic"]
        data = msg["data"]
        
        if "publicTrade" in topic:
            return [{"type": "trade", "symbol": data[0]["symbol"] if isinstance(data, list) else data["symbol"], "data": data}]
        elif "kline" in topic:
            if isinstance(data, list):
                return [{"type": "kline", "symbol": d["symbol"], "data": d} for d in data if d.get("confirm")]
            elif data.get("confirm"):
                return [{"type": "kline", "symbol": data["symbol"], "data": data}]
        elif "orderbook" in topic:
            return [{"type": "depth", "symbol": msg["topic"].split(".")[-1], "data": data}]
        
        return None
    
    async def _handle_event(self, event: dict):
        ev_type = event["type"]
        symbol = event["symbol"]
        data = event["data"]
        
        if ev_type == "trade":
            if isinstance(data, list):
                for d in data:
                    await self._process_trade(symbol, d)
            else:
                await self._process_trade(symbol, data)
        elif ev_type == "kline":
            await self._process_kline(symbol, data)
        elif ev_type == "depth":
            await self._process_depth(symbol, data)
    
    async def _process_trade(self, symbol: str, data: dict):
        price = float(data["price"])
        qty = float(data["size"])
        timestamp = data["time"]
        side = data["side"]
        
        buf = self._bar_buffers[symbol]
        interval_start = (timestamp // self._bar_interval_ms) * self._bar_interval_ms
        
        if buf['start_ts'] != interval_start:
            if buf['open'] is not None:
                await self._emit_bar(symbol, buf)
            buf.update({
                'open': price, 'high': price, 'low': price, 'close': price,
                'volume': qty, 'trades': 1, 'start_ts': interval_start
            })
        else:
            buf['high'] = max(buf['high'], price)
            buf['low'] = min(buf['low'], price)
            buf['close'] = price
            buf['volume'] += qty
            buf['trades'] += 1
    
    async def _process_kline(self, symbol: str, data: dict):
        if not data.get("confirm"):
            return
        bar = Bar(
            symbol=symbol,
            timestamp=data["start"],
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=float(data["volume"]),
            trades=data.get("tradeNum", 0)
        )
        if self.on_bar:
            self.on_bar(bar)
    
    async def _process_depth(self, symbol: str, data: dict):
        if self.on_orderbook:
            snapshot = OrderBookSnapshot(
                symbol=symbol,
                timestamp=data["ts"],
                bids=[(float(p), float(s)) for p, s in data["b"]],
                asks=[(float(p), float(s)) for p, s in data["a"]]
            )
            self.on_orderbook(snapshot)
    
    async def _emit_bar(self, symbol: str, buf: dict):
        bar = Bar(
            symbol=symbol,
            timestamp=buf['start_ts'],
            open=buf['open'],
            high=buf['high'],
            low=buf['low'],
            close=buf['close'],
            volume=buf['volume'],
            trades=buf['trades']
        )
        if self.on_bar:
            self.on_bar(bar)


class MultiExchangeProvider:
    """Manage multiple WebSocket providers with 24/7 supervision"""
    
    def __init__(self):
        self.providers: List[BaseWSProvider] = []
        self._supervise_tasks: List[asyncio.Task] = []
    
    def add_provider(self, provider: BaseWSProvider):
        self.providers.append(provider)
    
    async def start_all(self):
        """Start all providers with indefinite auto-reconnect loops."""
        tasks = [p.connect() for p in self.providers]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def start_all_supervised(self):
        """Start all providers plus per-provider health supervision (24/7).

        Each provider's connect() runs its own indefinite reconnect loop.
        This additionally starts a supervise() task per provider that detects
        stale connections and forces a reconnect when no data flows.
        """
        # Start per-provider supervision tasks
        for p in self.providers:
            self._supervise_tasks.append(asyncio.create_task(p.supervise()))
        
        # Start all provider connect loops
        tasks = [p.connect() for p in self.providers]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def stop_all(self):
        for p in self.providers:
            await p.stop()
        for task in self._supervise_tasks:
            task.cancel()
        await asyncio.gather(*self._supervise_tasks, return_exceptions=True)
        self._supervise_tasks = []
    
    def get_health_status(self) -> Dict[str, bool]:
        return {f"{type(p).__name__}:{p.symbols[:3]}": p.is_healthy() for p in self.providers}
    
    def get_status(self) -> List[dict]:
        """Get detailed status for all providers"""
        return [p.get_status() for p in self.providers]


# Factory function
def create_ws_provider(
    exchange: str,
    symbols: List[str],
    on_bar: Callable[[Bar], None],
    on_orderbook: Optional[Callable[[OrderBookSnapshot], None]] = None,
    on_trade: Optional[Callable[[dict], None]] = None,
    **kwargs
) -> BaseWSProvider:
    """Factory to create WebSocket provider"""
    exchange = exchange.lower()
    if exchange in ("binance", "binance_spot"):
        return BinanceWSProvider(symbols, on_bar, on_orderbook, on_trade, futures=False, **kwargs)
    elif exchange in ("binance_futures", "binance_fut"):
        return BinanceWSProvider(symbols, on_bar, on_orderbook, on_trade, futures=True, **kwargs)
    elif exchange in ("bybit", "bybit_linear"):
        return BybitWSProvider(symbols, on_bar, on_orderbook, on_trade, **kwargs)
    elif exchange in ("bybit_spot",):
        # Bybit spot uses different endpoint
        return BybitWSProvider(symbols, on_bar, on_orderbook, on_trade, **kwargs)
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")


# Example usage
async def main():
    """Example usage"""
    def on_bar(bar: Bar):
        print(f"Bar: {bar.symbol} O={bar.open} H={bar.high} L={bar.low} C={bar.close} V={bar.volume}")
    
    def on_orderbook(ob: OrderBookSnapshot):
        print(f"OB {ob.symbol}: bid={ob.bids[0][0] if ob.bids else 'N/A'} ask={ob.asks[0][0] if ob.asks else 'N/A'}")
    
    # Create providers
    binance = create_ws_provider("binance", ["BTCUSDT", "ETHUSDT"], on_bar)
    bybit = create_ws_provider("bybit", ["BTCUSDT", "ETHUSDT"], on_bar, on_orderbook)
    
    manager = MultiExchangeProvider()
    manager.add_provider(binance)
    manager.add_provider(bybit)
    
    try:
        await manager.start_all()
    except KeyboardInterrupt:
        await manager.stop_all()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
