import sys
import time
import aiohttp
sys.path.insert(0, '/Users/aryanagarwal/openalice-fleet/trading_terminal')
from ai.service import AIService
import asyncio

async def test():
    service = AIService()
    # Create HTTP session
    service._session = aiohttp.ClientSession()
    try:
        print("Providers:")
        for p in service._providers:
            print(f"  {p.name}: enabled={p.enabled}, base_url={p.base_url}")
        ollama_provider = None
        for p in service._providers:
            if p.name == "ollama":
                ollama_provider = p
                break
        if not ollama_provider:
            print("Ollama provider not found or not enabled")
            return
        print("\nTesting Ollama provider...")
        prompt = "Say hello in JSON format: {\"message\": \"hello\"}"
        start = time.time()
        try:
            result = await service._call_ai_provider(ollama_provider, prompt)
            elapsed = time.time() - start
            print(f"Ollama response (took {elapsed:.2f}s):")
            print(result)
            if result:
                print("Parsed successfully.")
                # Check if it's a dict with expected keys
                if isinstance(result, dict):
                    print("Keys:", list(result.keys()))
            else:
                print("Failed to get valid response.")
        except Exception as e:
            print(f"Error calling Ollama: {e}")
            import traceback
            traceback.print_exc()
    finally:
        await service._session.close()

if __name__ == "__main__":
    asyncio.run(test())
