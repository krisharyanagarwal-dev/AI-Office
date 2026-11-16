"""
Live Broker Implementations
Supports Binance, Bybit, Interactive Brokers, Alpaca, Coinbase
"""
import asyncio
import hmac
import hashlib
import time
import uuid
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import httpx
import websockets
import orjson
import hashlib

from .execution_engine import (
    BaseBroker, Order, OrderSide, OrderType, OrderStatus, 
    TimeInForce, Fill, Position, Fill, PaperBroker
)

logger = logging.getLogger(__name__)


class LiveBroker(BaseBroker):
    """Base class for live brokers"""
    
    def __init__(self, name: str, api_key: str, api_secret: str, 
                 testnet: bool = False, passphrase: str = ""):
        super().__init__(name, paper_trading=False)
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.testnet = testnet
        self._client: Optional[httpx.AsyncClient] = None
        self._ws = None
        self._listen_key = None
        self._last_update_id = 0
        
    @abstractmethod
    async def _initialize_client(self):
        """Initialize HTTP client and WebSocket"""
        pass
    
    @abstractmethod
    async def _sign_request(self, params: dict) -> dict:
        """Sign request for authenticated endpoints"""
        pass
    
    @abstractmethod
    async def _place_order(self, order: Order) -> dict:
        """Place order on exchange"""
        pass
    
    @abstractmethod
    async def _cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel order on exchange"""
        pass
    
    @abstractmethod
    async def _get_order_status(self, order_id: str, symbol: str) -> OrderStatus:
        pass
    
    @abstractmethod
    async def _get_account_info(self) -> dict:
        """Get account balances and positions"""
        pass
    
    @abstractmethod
    async def _get_exchange_info(self) -> dict:
        """Get exchange trading rules"""
        pass
    
    async def submit_order(self, order: Order) -> Order:
        # Pre-trade validation
        if not self._pre_trade_checks(order):
            order.status = OrderStatus.REJECTED
            await self._update_order(order)
            return order
        
        order.status = OrderStatus.SUBMITTED
        await self._update_order(order)
        
        try:
            result = await self._place_order(order)
            order.exchange_order_id = result.get('orderId') or result.get('order_id')
            order.status = OrderStatus.SUBMITTED
            await self._update_order(order)
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            order.status = OrderStatus.REJECTED
            await self._update_order(order)
        
        return order
    
    def _pre_trade_checks(self, order: Order) -> bool:
        """Basic pre-trade checks"""
        if order.quantity <= 0:
            return False
        if order.order_type == OrderType.LIMIT and not order.price:
            return False
        return True
    
    async def cancel_order(self, order_id: str, symbol: str = "") -> bool:
        order = self.orders.get(order_id)
        if not order or not order.is_active:
            return False
        
        try:
            result = await self._cancel_order(order.exchange_order_id or order_id, symbol or order.symbol)
            if result:
                order.status = OrderStatus.CANCELLED
                await self._update_order(order)
            return result
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return False
    
    async def get_order_status(self, order_id: str) -> OrderStatus:
        order = self.orders.get(order_id)
        if not order:
            return OrderStatus.REJECTED
        
        if order.exchange_order_id:
            try:
                status = await self._get_order_status(order.exchange_order_id, order.symbol)
                order.status = status
                await self._update_order(order)
                return status
            except Exception as e:
                logger.error(f"Status check failed: {e}")
        
        return order.status
    
    async def get_positions(self) -> Dict[str, Position]:
        return dict(self.positions)
    
    async def get_balances(self) -> Dict[str, float]:
        info = await self._get_account_info()
        balances = {}
        for asset in info.get('balances', []):
            free = float(asset.get('free', 0))
            locked = float(asset.get('locked', 0))
            if free > 0 or locked > 0:
                balances[asset['asset']] = free + locked
        return balances
    
    async def start(self):
        """Start the broker (connect WS, start listen key)"""
        await self._initialize_client()
        await self._start_user_stream()
    
    async def stop(self):
        """Stop the broker"""
        if self._ws:
            await self._ws.close()
        if self._client:
            await self._client.aclose()
        if self._listen_key:
            await self._close_user_stream()
    
    @abstractmethod
    async def _start_user_stream(self):
        """Start user data stream (WebSocket)"""
        pass
    
    @abstractmethod
    async def _close_user_stream(self):
        """Close user data stream"""
        pass
    
    @abstractmethod
    async def _handle_user_stream(self, msg: dict):
        """Handle user stream messages (orders, fills, balances)"""
        pass


class BinanceBroker(LiveBroker):
    """Binance Spot and Futures Broker"""
    
    def __init__(self, api_key: str, api_secret: str, 
                 futures: bool = False, testnet: bool = False, **kwargs):
        super().__init__("binance", api_key, api_secret, testnet, **kwargs)
        self.futures = futures
        self.base_url = "https://testnet.binancefuture.com" if futures and testnet else \
                       "https://fapi.binance.com" if futures else \
                       "https://testnet.binance.vision" if testnet else "https://api.binance.com"
        self.ws_url = "wss://fstream.binance.com/ws" if futures else "wss://stream.binance.com:9443/ws"
        if testnet:
            self.ws_url = "wss://stream.binancefuture.com/ws" if futures else "wss://testnet.binance.vision/ws"
    
    async def _initialize_client(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            headers={'X-MBX-APIKEY': self.api_key}
        )
        # Test connectivity
        await self._client.get("/fapi/v1/ping" if self.futures else "/api/v3/ping")
        await self._get_exchange_info()
    
    def _sign_params(self, params: dict) -> dict:
        """Sign parameters for authenticated requests"""
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        params['signature'] = signature
        params['timestamp'] = int(time.time() * 1000)
        return params
    
    async def _sign_request(self, params: dict) -> dict:
        return self._sign_params(params)
    
    async def _get_exchange_info(self):
        endpoint = "/fapi/v1/exchangeInfo" if self.futures else "/api/v3/exchangeInfo"
        resp = await self._client.get(endpoint)
        self.exchange_info = resp.json()
    
    def _get_symbol_info(self, symbol: str) -> dict:
        for s in self.exchange_info.get('symbols', []):
            if s['symbol'] == symbol:
                return s
        return {}
    
    def _round_quantity(self, symbol: str, qty: float) -> float:
        """Round quantity to symbol's step size"""
        info = self._get_symbol_info(symbol)
        for f in info.get('filters', []):
            if f['filterType'] == 'LOT_SIZE':
                step_size = float(f['stepSize'])
                precision = len(str(step_size).split('.')[-1].rstrip('0'))
                return round(qty / step_size) * step_size
        return qty
    
    async def _place_order(self, order: Order) -> dict:
        symbol = order.symbol
        qty = self._round_quantity(symbol, order.quantity)
        
        params = {
            'symbol': symbol,
            'side': order.side.value.upper(),
            'type': order.order_type.value.upper(),
            'quantity': str(qty),
        }
        
        if order.order_type == OrderType.LIMIT:
            params['price'] = f"{order.price:.8f}"
            params['timeInForce'] = order.time_in_force.value.upper()
        elif order.order_type == OrderType.STOP_LIMIT:
            params['price'] = f"{order.price:.8f}"
            params['stopPrice'] = f"{order.stop_price:.8f}"
            params['timeInForce'] = order.time_in_force.value.upper()
        elif order.order_type == OrderType.STOP:
            params['stopPrice'] = f"{order.stop_price:.8f}"
        
        params = self._sign_params(params)
        
        endpoint = "/fapi/v1/order" if self.futures else "/api/v3/order"
        resp = await self._client.post(endpoint, data=params)
        resp.raise_for_status()
        return resp.json()
    
    async def _cancel_order(self, order_id: str, symbol: str) -> bool:
        params = {'symbol': symbol, 'orderId': order_id}
        params = self._sign_params(params)
        
        endpoint = "/fapi/v1/order" if self.futures else "/api/v3/order"
        resp = await self._client.delete(endpoint, params=params)
        return resp.status_code == 200
    
    async def _get_order_status(self, order_id: str, symbol: str) -> OrderStatus:
        params = {'symbol': symbol, 'orderId': order_id}
        params = self._sign_params(params)
        
        endpoint = "/fapi/v1/order" if self.futures else "/api/v3/order"
        resp = await self._client.get(endpoint, params=params)
        data = resp.json()
        
        status_map = {
            'NEW': OrderStatus.SUBMITTED,
            'PARTIALLY_FILLED': OrderStatus.PARTIAL,
            'FILLED': OrderStatus.FILLED,
            'CANCELED': OrderStatus.CANCELLED,
            'REJECTED': OrderStatus.REJECTED,
            'EXPIRED': OrderStatus.EXPIRED
        }
        return status_map.get(data.get('status'), OrderStatus.PENDING)
    
    async def _get_account_info(self) -> dict:
        params = {}
        params = self._sign_params(params)
        
        endpoint = "/fapi/v2/account" if self.futures else "/api/v3/account"
        resp = await self._client.get(endpoint, params=params)
        return resp.json()
    
    async def _start_user_stream(self):
        """Start user data stream"""
        endpoint = "/fapi/v1/listenKey" if self.futures else "/api/v3/userDataStream"
        resp = await self._client.post(endpoint)
        data = resp.json()
        self._listen_key = data['listenKey']
        
        # Start WebSocket
        self._ws = await websockets.connect(f"{self.ws_url}/{self._listen_key}")
        asyncio.create_task(self._listen_user_stream())
        
        # Keepalive
        asyncio.create_task(self._keepalive_listen_key())
    
    async def _keepalive_listen_key(self):
        while self._listen_key:
            await asyncio.sleep(30 * 60)  # 30 minutes
            try:
                endpoint = "/fapi/v1/listenKey" if self.futures else "/api/v3/userDataStream"
                await self._client.put(endpoint, params={'listenKey': self._listen_key})
            except Exception as e:
                logger.error(f"Listen key keepalive failed: {e}")
    
    async def _listen_user_stream(self):
        try:
            async for msg in self._ws:
                data = orjson.loads(msg)
                await self._handle_user_stream(data)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("User stream closed, reconnecting...")
            await asyncio.sleep(5)
            await self._start_user_stream()
    
    async def _handle_user_stream(self, msg: dict):
        e = msg.get('e')
        if e == 'ORDER_TRADE_UPDATE':
            o = msg['o']
            order_id = o.get('c')  # client order id
            exchange_order_id = str(o.get('i'))
            status = o.get('X')
            
            # Find local order
            order = None
            for o in self.orders.values():
                if o.exchange_order_id == exchange_order_id or o.client_order_id == order_id:
                    order = o
                    break
            
            if order:
                status_map = {
                    'NEW': OrderStatus.SUBMITTED,
                    'PARTIALLY_FILLED': OrderStatus.PARTIAL,
                    'FILLED': OrderStatus.FILLED,
                    'CANCELED': OrderStatus.CANCELLED,
                    'REJECTED': OrderStatus.REJECTED,
                    'EXPIRED': OrderStatus.EXPIRED
                }
                order.status = status_map.get(status, order.status)
                
                if status == 'FILLED':
                    order.filled_qty = float(o['z'])
                    order.avg_fill_price = float(o['ap'])
                    order.commission = float(o.get('n', 0))
                    order.status = OrderStatus.FILLED
                
                elif status == 'PARTIALLY_FILLED':
                    order.filled_qty = float(o['z'])
                    order.avg_fill_price = float(o['ap'])
                    order.status = OrderStatus.PARTIAL
                
                await self._update_order(order)
                
        elif e == 'ACCOUNT_UPDATE':
            for a in msg['a']['B']:
                asset = a['a']
                free = float(a['w'])
                locked = float(a.get('wb', 0))
                if asset not in self.balances or self.balances[asset] != free + locked:
                    self.balances[asset] = free + locked
        
        elif e == 'ORDER_TRADE_UPDATE' and 'l' in msg['o']:  # Fill
            o = msg['o']
            fill = Fill(
                order_id=o['c'],
                symbol=o['s'],
                side=OrderSide.BUY if o['S'] == 'BUY' else OrderSide.SELL,
                quantity=float(o['l']),
                price=float(o['L']),
                commission=float(o.get('n', 0)),
                timestamp=int(o['T']) / 1000,
                exchange_fill_id=str(o['t'])
            )
            await self._process_fill(fill)


class BybitBroker(LiveBroker):
    """Bybit V5 Broker (Linear/Inverse/Spot/Options)"""
    
    def __init__(self, api_key: str, api_secret: str, 
                 testnet: bool = False, category: str = "linear", **kwargs):
        super().__init__("bybit", api_key, api_secret, testnet)
        self.category = category  # linear, inverse, spot, option
        self.base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
        self.ws_url = "wss://stream-testnet.bybit.com/v5/public/linear" if testnet else "wss://stream.bybit.com/v5/public/linear"
        self.private_ws_url = "wss://stream-testnet.bybit.com/v5/private" if testnet else "wss://stream.bybit.com/v5/private"
    
    async def _initialize_client(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0
        )
        await self._client.get("/v5/market/time")
    
    def _sign_request(self, params: dict) -> dict:
        timestamp = str(int(time.time() * 1000))
        recv_window = "5000"
        param_str = f"{timestamp}{self.api_key}{recv_window}" + '&'.join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            param_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            'X-BAPI-API-KEY': self.api_key,
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_window,
            'X-BAPI-SIGN': signature,
            'Content-Type': 'application/json'
        }
        return headers
    
    async def _place_order(self, order: Order) -> dict:
        params = {
            'category': self.category,
            'symbol': order.symbol,
            'side': order.side.value.capitalize(),
            'orderType': order.order_type.value.capitalize(),
            'qty': str(order.quantity),
        }
        
        if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
            params['price'] = str(order.price)
        if order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            params['triggerPrice'] = str(order.stop_price)
        if order.time_in_force != TimeInForce.GTC:
            params['timeInForce'] = order.time_in_force.value.upper()
        
        headers = self._sign_request(params)
        resp = await self._client.post("/v5/order/create", json=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    
    async def _cancel_order(self, order_id: str, symbol: str) -> bool:
        params = {'category': self.category, 'symbol': symbol, 'orderId': order_id}
        headers = self._sign_request(params)
        resp = await self._client.post("/v5/order/cancel", json=params, headers=headers)
        return resp.json().get('retCode') == 0
    
    async def _get_order_status(self, order_id: str, symbol: str) -> OrderStatus:
        params = {'category': self.category, 'symbol': symbol, 'orderId': order_id}
        headers = self._sign_request(params)
        resp = await self._client.get("/v5/order/realtime", params=params, headers=headers)
        data = resp.json().get('result', {}).get('list', [{}])[0]
        
        status_map = {
            'New': OrderStatus.SUBMITTED,
            'PartiallyFilled': OrderStatus.PARTIAL,
            'Filled': OrderStatus.FILLED,
            'Cancelled': OrderStatus.CANCELLED,
            'Rejected': OrderStatus.REJECTED
        }
        return status_map.get(data.get('orderStatus'), OrderStatus.PENDING)
    
    async def _get_account_info(self) -> dict:
        headers = self._sign_request({})
        resp = await self._client.get("/v5/account/wallet-balance", params={'accountType': 'UNIFIED'}, headers=headers)
        return resp.json()
    
    async def _get_exchange_info(self):
        resp = await self._client.get(f"/v5/market/instruments-info?category={self.category}")
        self.exchange_info = resp.json()
    
    async def _start_user_stream(self):
        # Bybit private WebSocket
        pass  # Implementation similar to Binance


class InteractiveBrokersBroker(LiveBroker):
    """Interactive Brokers Broker (requires ib_insync or ibapi)"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1, **kwargs):
        super().__init__("ibkr", "", "", False)
        self.host = host
        self.port = port
        self.client_id = client_id
        self._ib = None
    
    async def _initialize_client(self):
        try:
            from ib_insync import IB, Stock, Future, Option, Forex, CFD, Crypto
            self._ib = IB()
            await self._ib.connectAsync(self.host, self.port, self.client_id)
            logger.info("Connected to IBKR")
        except ImportError:
            logger.error("ib_insync not installed. pip install ib_insync")
            raise
        except Exception as e:
            logger.error(f"IBKR connection failed: {e}")
            raise
    
    async def _place_order(self, order: Order) -> dict:
        from ib_insync import Order as IBOrder, MarketOrder, LimitOrder, StopOrder, StopLimitOrder
        
        ib_order = None
        if order.order_type == OrderType.MARKET:
            ib_order = MarketOrder(order.side.value.capitalize(), order.quantity)
        elif order.order_type == OrderType.LIMIT:
            ib_order = LimitOrder(order.side.value.capitalize(), order.quantity, order.price)
        elif order.order_type == OrderType.STOP:
            ib_order = StopOrder(order.side.value.capitalize(), order.quantity, order.stop_price)
        elif order.order_type == OrderType.STOP_LIMIT:
            ib_order = StopLimitOrder(order.side.value.capitalize(), order.quantity, order.price, order.stop_price)
        
        if order.time_in_force != TimeInForce.GTC:
            ib_order.tif = order.time_in_force.value.upper()
        
        trade = await self._ib.placeOrderAsync(
            self._get_contract(order.symbol), ib_order
        )
        
        return {'orderId': str(trade.order.orderId), 'clientOrderId': str(trade.order.permId)}
    
    def _get_contract(self, symbol: str):
        from ib_insync import Stock, Future, Option, Forex, Crypto
        # Simplified - would need proper symbol parsing
        return Stock(symbol, 'SMART', 'USD')
    
    async def _cancel_order(self, order_id: str, symbol: str) -> bool:
        # Would need to track IB order IDs
        return True
    
    async def _get_order_status(self, order_id: str, symbol: str):
        pass
    
    async def _get_account_info(self):
        pass
    
    async def _get_exchange_info(self):
        pass
    
    async def _start_user_stream(self):
        pass
    
    async def _close_user_stream(self):
        pass
    
    async def _handle_user_stream(self, msg):
        pass


class AlpacaBroker(LiveBroker):
    """Alpaca Markets Broker (US Equities, Crypto)"""
    
    def __init__(self, api_key: str, api_secret: str, 
                 paper: bool = True, **kwargs):
        super().__init__("alpaca", api_key, api_secret, paper)
        self.paper = paper
        self.base_url = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        self.data_url = "https://data.alpaca.markets"
        self.ws_url = "wss://paper-api.alpaca.markets/stream" if paper else "wss://api.alpaca.markets/stream"
    
    async def _initialize_client(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            headers={
                'APCA-API-KEY-ID': self.api_key,
                'APCA-API-SECRET-KEY': self.api_secret
            }
        )
        await self._client.get("/v2/account")
    
    def _sign_request(self, params: dict) -> dict:
        # Alpaca uses API key in headers, not signing
        return {}
    
    async def _place_order(self, order: Order) -> dict:
        params = {
            'symbol': order.symbol,
            'qty': str(order.quantity),
            'side': order.side.value.lower(),
            'type': order.order_type.value.lower(),
            'time_in_force': order.time_in_force.value.lower(),
        }
        
        if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
            params['limit_price'] = str(order.price)
        if order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            params['stop_price'] = str(order.stop_price)
        
        resp = await self._client.post("/v2/orders", json=params)
        resp.raise_for_status()
        return resp.json()
    
    async def _cancel_order(self, order_id: str, symbol: str) -> bool:
        resp = await self._client.delete(f"/v2/orders/{order_id}")
        return resp.status_code == 204
    
    async def _get_order_status(self, order_id: str, symbol: str) -> OrderStatus:
        resp = await self._client.get(f"/v2/orders/{order_id}")
        data = resp.json()
        
        status_map = {
            'new': OrderStatus.SUBMITTED,
            'partially_filled': OrderStatus.PARTIAL,
            'filled': OrderStatus.FILLED,
            'canceled': OrderStatus.CANCELLED,
            'rejected': OrderStatus.REJECTED,
            'expired': OrderStatus.EXPIRED
        }
        return status_map.get(data.get('status'), OrderStatus.PENDING)
    
    async def _get_account_info(self):
        resp = await self._client.get("/v2/account")
        return resp.json()
    
    async def _get_exchange_info(self):
        resp = await self._client.get("/v2/assets")
        self.exchange_info = {'assets': resp.json()}
    
    async def _start_user_stream(self):
        pass
    
    async def _close_user_stream(self):
        pass
    
    async def _handle_user_stream(self, msg):
        pass


class CoinbaseBroker(LiveBroker):
    """Coinbase Advanced Trade Broker"""
    
    def __init__(self, api_key: str, api_secret: str, 
                 sandbox: bool = False, **kwargs):
        super().__init__("coinbase", api_key, api_secret, sandbox)
        self.base_url = "https://api-sandbox.coinbase.com" if sandbox else "https://api.coinbase.com"
        self.ws_url = "wss://advanced-trade-ws.coinbase.com"
    
    async def _initialize_client(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0
        )
        await self._client.get("/api/v3/brokerage/accounts")
    
    def _sign_request(self, params: dict) -> dict:
        timestamp = str(int(time.time()))
        message = f"{timestamp}POST/api/v3/brokerage/orders{orjson.dumps(params).decode()}"
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return {
            'CB-ACCESS-KEY': self.api_key,
            'CB-ACCESS-SIGN': signature,
            'CB-ACCESS-TIMESTAMP': str(int(time.time())),
            'Content-Type': 'application/json'
        }
    
    async def _place_order(self, order: Order) -> dict:
        params = {
            'client_order_id': order.client_order_id,
            'product_id': order.symbol.replace('/', '-'),
            'side': order.side.value.upper(),
            'order_configuration': {}
        }
        
        if order.order_type == OrderType.MARKET:
            params['order_configuration'] = {
                'market_market_ioc': {'base_size': str(order.quantity)}
            }
        elif order.order_type == OrderType.LIMIT:
            params['order_configuration'] = {
                'limit_limit_gtc': {
                    'base_size': str(order.quantity),
                    'limit_price': str(order.price)
                }
            }
        
        headers = self._sign_request(params)
        resp = await self._client.post("/api/v3/brokerage/orders", json=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    
    async def _cancel_order(self, order_id: str, symbol: str) -> bool:
        headers = self._sign_request({})
        resp = await self._client.delete(f"/api/v3/brokerage/orders/{order_id}", headers=headers)
        return resp.status_code == 200
    
    async def _get_order_status(self, order_id: str, symbol: str) -> OrderStatus:
        headers = self._sign_request({})
        resp = await self._client.get(f"/api/v3/brokerage/orders/{order_id}", headers=headers)
        data = resp.json()
        
        status_map = {
            'OPEN': OrderStatus.SUBMITTED,
            'FILLED': OrderStatus.FILLED,
            'CANCELLED': OrderStatus.CANCELLED,
            'EXPIRED': OrderStatus.EXPIRED,
            'FAILED': OrderStatus.REJECTED
        }
        return status_map.get(data.get('order', {}).get('status'), OrderStatus.PENDING)
    
    async def _get_account_info(self):
        headers = self._sign_request({})
        resp = await self._client.get("/api/v3/brokerage/accounts", headers=headers)
        return resp.json()
    
    async def _get_exchange_info(self):
        pass
    
    async def _start_user_stream(self):
        pass
    
    async def _close_user_stream(self):
        pass
    
    async def _handle_user_stream(self, msg):
        pass


class BrokerFactory:
    """Factory for creating broker instances"""
    
    _brokers = {
        'binance': BinanceBroker,
        'binance_futures': BinanceBroker,
        'bybit': BybitBroker,
        'ibkr': InteractiveBrokersBroker,
        'alpaca': AlpacaBroker,
        'coinbase': CoinbaseBroker,
        'paper': PaperBroker,  # From execution_engine
    }
    
    @classmethod
    def create(cls, broker_type: str, **kwargs) -> LiveBroker:
        broker_class = cls._brokers.get(broker_type.lower())
        if not broker_class:
            raise ValueError(f"Unknown broker: {broker_type}")
        return broker_class(**kwargs)
    
    @classmethod
    def register(cls, name: str, broker_class):
        cls._brokers[name.lower()] = broker_class


# Multi-broker manager for redundancy
class MultiBrokerManager:
    """Manage multiple brokers with failover"""
    
    def __init__(self):
        self.brokers: Dict[str, LiveBroker] = {}
        self.primary: Optional[str] = None
        self.failover_order: List[str] = []
    
    def add_broker(self, name: str, broker: LiveBroker, is_primary: bool = False):
        self.brokers[name] = broker
        if is_primary or not self.primary:
            self.primary = name
        if name not in self.failover_order:
            self.failover_order.append(name)
    
    async def start_all(self):
        for b in self.brokers.values():
            await b.start()
    
    async def stop_all(self):
        for b in self.brokers.values():
            await b.stop()
    
    async def submit_order(self, order: Order) -> Order:
        """Submit with failover"""
        for name in self.failover_order:
            broker = self.brokers[name]
            try:
                result = await broker.submit_order(order)
                if result.status != OrderStatus.REJECTED:
                    return result
            except Exception as e:
                logger.warning(f"Broker {name} failed: {e}, trying next...")
                continue
        
        # All failed
        order.status = OrderStatus.REJECTED
        return order
    
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        for name in self.failover_order:
            broker = self.brokers[name]
            if await broker.cancel_order(order_id):
                return True
        return False
    
    def get_balances_all(self) -> Dict[str, Dict[str, float]]:
        return {name: b.get_balances() for name, b in self.brokers.items()}


# Helper to create broker from config
def create_broker_from_config(config: dict) -> LiveBroker:
    """Create broker from config dict"""
    broker_type = config.get('type', 'paper')
    
    if broker_type == 'paper':
        from alpha.execution.execution_engine import PaperBroker
        return PaperBroker(initial_balance=config.get('initial_balance', 100000))
    
    return BrokerFactory.create(
        config['type'],
        api_key=config.get('api_key'),
        api_secret=config.get('api_secret'),
        testnet=config.get('testnet', False),
        **config.get('params', {})
    )


# Example usage
async def main():
    # Create broker from config
    config = {
        'type': 'binance',
        'api_key': 'your_api_key',
        'api_secret': 'your_api_secret',
        'testnet': True,
        'params': {'futures': True}
    }
    
    broker = create_broker_from_config(config)
    await broker.start()
    
    # Submit order
    order = Order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=0.01,
        price=50000.0
    )
    
    result = await broker.submit_order(order)
    print(f"Order: {result.status}, ID: {result.exchange_order_id}")
    
    await broker.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
