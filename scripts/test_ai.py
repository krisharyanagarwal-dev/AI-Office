import sys
sys.path.insert(0, '/Users/aryanagarwal/openalice-fleet/trading_terminal')
from ai.service import AIService
import asyncio

async def test():
    service = AIService()
    market_data = await service._gather_market_data()
    print("Market data keys:", list(market_data.keys()) if market_data else None)
    if market_data:
        # Show some values
        pipeline = market_data.get("pipeline", {})
        tape = market_data.get("tape", {})
        algo20 = market_data.get("algo20", {})
        freetrader = market_data.get("freetrader", {})
        print("Pipeline ts:", pipeline.get("ts"))
        print("Tape ts:", tape.get("ts"))
        print("Algo20 ts:", algo20.get("ts"))
        print("Freetrader ts:", freetrader.get("ts"))
        prompt = service._create_analysis_prompt(market_data)
        print("\n=== PROMPT ===")
        print(prompt)
        print("\n=== END PROMPT ===")
    else:
        print("No market data")
        # Maybe we need to run the service briefly? Let's just return.
        
if __name__ == "__main__":
    asyncio.run(test())
