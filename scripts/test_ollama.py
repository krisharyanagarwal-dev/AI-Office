import sys
import time
sys.path.insert(0, '/Users/aryanagarwal/openalice-fleet/trading_terminal')
from ai.service import AIService
import asyncio

async def test():
    service = AIService()
    print("Providers:")
    for p in service._providers:
        print(f"  {p.name}: enabled={p.enabled}, base_url={p.base_url}")
    # Find Ollama provider
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
        else:
            print("Failed to get valid response.")
    except Exception as e:
        print(f"Error calling Ollama: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
