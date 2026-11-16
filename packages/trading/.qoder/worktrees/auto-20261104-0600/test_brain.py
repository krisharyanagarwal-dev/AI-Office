"""
Test script for the trading brain
This verifies that the three brains work together correctly.
"""
import numpy as np
import time
from datetime import datetime, timedelta

from alpha.brain import (
    TradingBot,
    create_trading_bot,
    Bar,
    ChartContext,
    RegimeState,
    VolRegime,
    Positions,
    ChartBrain,
    DecisionBrain,
    LearningBrain,
    Decision,
    Fill,
    PnL,
    StateStore
)

def generate_test_bars(n_bars: int = 1000, symbol: str = "BTCUSDT") -> list:
    """Generate synthetic OHLCV data for testing"""
    bars = []

    # Start price
    price = 50000.0  # Starting BTC price
    
    # Generate trending then mean-reverting pattern
    for i in range(n_bars):
        # Create cyclic pattern: trend up, chop, trend down, chop
        cycle_pos = (i % 200) / 200.0
        
        if cycle_pos < 0.3:  # Trend up
            trend = 0.002
        elif cycle_pos < 0.5:  # Chop
            trend = 0.0
        elif cycle_pos < 0.8:  # Trend down
            trend = -0.0015
        else:  # Chop
            trend = 0.0
            
        # Add some noise
        noise = np.random.normal(0, 0.01)
        return_pct = trend + noise
        
        # OHLCV
        open_price = price
        close_price = price * (1 + return_pct)
        high_price = max(open_price, close_price) * (1 + abs(np.random.normal(0, 0.005)))
        low_price = min(open_price, close_price) * (1 - abs(np.random.normal(0, 0.005)))
        volume = np.random.uniform(100, 1000)
        
        timestamp = datetime.now() - timedelta(minutes=n_bars-i)
        
        bar = Bar(
            timestamp=int(timestamp.timestamp()),
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume
        )
        
        bars.append(bar)
        price = close_price
        
    return bars

def test_brain_components():
    """Test each brain component individually and together"""
    print("🧠 TESTING TRADING BRAIN ARCHITECTURE 🧠")
    print("=" * 50)
    
    # Test data
    bars = generate_test_bars(500, "TEST")
    
    # 1. Test Chart Brain
    print("\n1. Testing Chart Brain...")
    chart_brain = ChartBrain(symbol="TEST")
    ctx = None
    
    # Process bars through chart brain
    for bar in bars[-50:]:  # Last 50 bars
        ctx = chart_brain.update(bar)
    
    if ctx:
        print(f"   Final regime: {ctx.regime.value} (confidence: {ctx.regime_confidence:.2f})")
        print(f"   Vol regime: {ctx.vol_regime.value}")
        print(f"   ATR: {ctx.atr:.1f}")
        print(f"   Trend strength: {ctx.trend_strength:.1f}")
        print(f"   RSI: {ctx.rsi:.1f}")
        print(f"   Patterns detected: {len(ctx.active_patterns)}")
        print(f"   S/R levels: {len(ctx.sr_levels)}")
    else:
        print("   ❌ Failed to generate context")
        return False
    
    # 2. Test Decision Brain
    print("\n2. Testing Decision Brain...")
    try:
        decision_brain = DecisionBrain({})
        positions = Positions()  # Would be Positions object in reality
        decision = decision_brain.decide(ctx, positions)
        
        print(f"   Decision rationale: {decision.rationale}")
        print(f"   Orders: {len(decision.orders)}")
        if decision.orders:
            order = decision.orders[0]
            print(f"   First order: {order.side} {order.quantity} {order.symbol} {order.order_type}")
        print(f"   Risk metrics keys: {list(decision.risk_metrics.keys())}")
        print("   ✅ Decision Brain test passed")
        test1_passed = True
    except Exception as e:
        print(f"   ❌ TEST FAILED WITH EXCEPTION: {e}")
        test1_passed = False
    
    # 3. Test Learning Brain
    try:
        learning_brain = LearningBrain({})
        # Simulate some trades
        for i in range(5):
            # Mock trade data
            decision = Decision(
                orders=[],
                rationale="test",
                risk_metrics={},
                meta={}
            )
            fill = Fill(
                order_id=f"order_{i}",
                symbol="TEST",
                side=1 if i % 2 == 0 else -1,
                quantity=0.1,
                price=50000.0 + i*100,
                timestamp=int(time.time()),
                commission=0.0
            )
            pnl = PnL(
                realized=np.random.normal(10, 20),
                unrealized=0.0,
                timestamp=int(time.time())
            )
            learning_brain.record_outcome(decision, fill, pnl)
        
        # Get performance stats
        stats = learning_brain.get_performance_stats()
        print(f"   Total trades: {stats.get('total_trades', 0)}")
        print(f"   Win rate: {stats.get('win_rate', 0):.2%}")
        print(f"   Net P&L: {stats.get('net_pnl', 0):.2f}")
        print("   ✅ Learning Brain test passed")
        test2_passed = True
    except Exception as e:
        print(f"   ❌ TEST FAILED WITH EXCEPTION: {e}")
        test2_passed = False

    # 4. Test Trading Bot (integration)
    try:
        state_store = StateStore()
        bot_config = {
            "max_position_pct": 0.1,
            "max_leverage": 3.0,
            "min_edge_bp": 5.0,
            "kelly_cap": 0.25
        }
        bot = create_trading_bot("TEST", config=bot_config, state_store=state_store)
        
        # Process bars using the bot's simulate_bar method
        for bar in bars[-30:]:
            bot.simulate_bar(bar)
        
        # Allow time for processing
        time.sleep(0.1)
        
        stats = bot.get_status()
        print(f"   Bars processed: {stats.get('bars_processed', 0)}")
        print(f"   Decisions made: {stats.get('decisions_made', 0)}")
        print(f"   Orders generated: {stats.get('orders_generated', 0)}")
        print("   ✅ Trading Bot test passed")
        test3_passed = True
    except Exception as e:
        print(f"   ❌ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        test3_passed = False
    
    # Summary
    print("\n" + "=" * 50)
    print("TEST SUMMARY:")
    print(f"  Chart Brain:     {'✅ PASS' if ctx else '❌ FAIL'}")
    print(f"  Decision Brain:  {'✅ PASS' if test1_passed else '❌ FAIL'}")
    print(f"  Learning Brain:  {'✅ PASS' if test2_passed else '❌ FAIL'}")
    print(f"  Trading Bot:     {'✅ PASS' if test3_passed else '❌ FAIL'}")
    
    all_passed = ctx and test1_passed and test2_passed and test3_passed
    print(f"\nOVERALL: {'🎉 ALL TESTS PASSED' if all_passed else '💥 SOME TESTS FAILED'}")
    return all_passed

if __name__ == "__main__":
    test_brain_components()
