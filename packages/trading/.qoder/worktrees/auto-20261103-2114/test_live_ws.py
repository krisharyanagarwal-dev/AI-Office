#!/usr/bin/env python3
"""
Test WebSocket connection to Binance (live) and integration with TradingBot
"""
import sys
import time
import logging
from alpha.data.ws_provider import BinanceWSProvider
from alpha.brain.trading_bot import create_trading_bot
from alpha.brain.state_store import StateStore

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global to count messages received
message_count = 0
last_message_time = None

def on_bar_callback(bar_data):
    """Callback function to handle incoming bar data"""
    global message_count, last_message_time
    message_count += 1
    last_message_time = time.time()
    if message_count <= 5:  # Only log first few messages to avoid spam
        logger.info(f"Received bar #{message_count}: {bar_data['symbol']} - O:{bar_data['open']:.2f} H:{bar_data['high']:.2f} L:{bar_data['low']:.2f} C:{bar_data['close']:.2f} V:{bar_data['volume']:.2f}")
    elif message_count % 10 == 0:  # Log every 10th message after that
        logger.info(f"Received bar #{message_count}: {bar_data['symbol']} - C:{bar_data['close']:.2f}")

def main():
    """Main test function"""
    logger.info("Testing Binance WebSocket connection (live) and TradingBot integration...")
    
    # Create state store
    state_store = StateStore()
    
    # Create TradingBot with paper trading=True
    bot_config = {
        'max_position_pct': 0.10,
        'max_leverage': 2.0,
        'enable_learning': True,
        'ws_provider': {
            'interval': '1m',
            'is_futures': False
        }
    }
    
    logger.info("Creating TradingBot...")
    bot = create_trading_bot(
        symbol="BTCUSDT",
        paper_trading=True,
        config=bot_config,
        state_store=state_store
    )
    
    # Override the bot's WS provider callback to use our counting callback
    # We need to recreate the WS provider with our callback
    bot.ws_provider.disconnect()  # Disconnect any existing connection
    
    # Create new WS provider with our callback
    ws_provider = BinanceWSProvider(
        symbols=["BTCUSDT"],
        callback=on_bar_callback,
        interval="1m",
        is_futures=False
    )
    
    # Replace the bot's WS provider
    bot.ws_provider = ws_provider
    
    try:
        # Start the bot
        logger.info("Starting TradingBot...")
        bot.start()
        
        # Wait for messages
        logger.info("Waiting for live data messages (60 seconds)...")
        start_time = time.time()
        timeout = 60  # seconds
        
        while time.time() - start_time < timeout:
            time.sleep(1)
            elapsed = int(time.time() - start_time)
            remaining = timeout - elapsed
            if elapsed % 10 == 0 and elapsed > 0:  # Log every 10 seconds
                logger.info(f"Time elapsed: {elapsed}s, Messages received: {message_count}, Remaining: {remaining}s")
        
        # Get final status
        logger.info("Getting final bot status...")
        status = bot.get_status()
        logger.info(f"Final status: Bars processed: {status.get('bars_processed', 0)}, "
                   f"Decisions made: {status.get('decisions_made', 0)}, "
                   f"Orders generated: {status.get('orders_generated', 0)}")
        
        # Stop the bot
        logger.info("Stopping TradingBot...")
        bot.stop()
        
        success = message_count > 0
        if success:
            logger.info(f"SUCCESS: Received {message_count} messages from Binance WebSocket")
        else:
            logger.warning("WARNING: No messages received from Binance WebSocket (might be normal if no new candles closed)")
        
        return success
        
    except Exception as e:
        logger.error(f"Error during live WebSocket test: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Ensure cleanup
        try:
            bot.stop()
        except:
            pass
        try:
            ws_provider.disconnect()
        except:
            pass

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
