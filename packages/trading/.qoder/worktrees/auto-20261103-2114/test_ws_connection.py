#!/usr/bin/env python3
"""
Test WebSocket connection to Binance testnet
"""
import sys
import time
import logging
from alpha.data.ws_provider import BinanceWSProvider

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def on_bar_callback(bar_data):
    """Callback function to handle incoming bar data"""
    logger.info(f"Received bar: {bar_data['symbol']} - O:{bar_data['open']} H:{bar_data['high']} L:{bar_data['low']} C:{bar_data['close']} V:{bar_data['volume']}")

def main():
    """Main test function"""
    logger.info("Testing Binance WebSocket connection to testnet...")
    
    # Create WebSocket provider for BTCUSDT on spot testnet
    # Note: Binance testnet uses the same websocket endpoint as mainnet for now
    # For true testnet, we might need to use a different approach or use Bybit testnet
    ws_provider = BinanceWSProvider(
        symbols=["BTCUSDT"],
        callback=on_bar_callback,
        interval="1m",
        is_futures=False
    )
    
    try:
        # Connect to WebSocket
        logger.info("Connecting to Binance WebSocket...")
        ws_provider.connect()
        
        # Wait for a few messages
        logger.info("Waiting for messages (30 seconds)...")
        time.sleep(30)
        
    except Exception as e:
        logger.error(f"Error during WebSocket test: {e}")
        return False
    finally:
        # Disconnect
        logger.info("Disconnecting from WebSocket...")
        ws_provider.disconnect()
    
    logger.info("WebSocket test completed successfully!")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
