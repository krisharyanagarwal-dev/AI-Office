import sys
import time
import aiohttp
sys.path.insert(0, '/Users/aryanagarwal/openalice-fleet/trading_terminal')
from ai.service import AIService
import asyncio

async def test():
    service = AIService()
    # Disable providers before ollama to force ollama usage
    for p in service._providers:
        if p.name in ["groq", "deepseek", "nim", "openrouter"]:
            p.enabled = False
        # keep ollama and localai as is (ollama enabled, localai enabled)
    # Create HTTP session
    service._session = aiohttp.ClientSession()
    try:
        print("Providers after modification:")
        for p in service._providers:
            print(f"  {p.name}: enabled={p.enabled}, base_url={p.base_url}")
        ollama_provider = None
        for p in service._providers:
            if p.name == "ollama":
                ollama_provider = p
                break
        if not ollama_provider or not ollama_provider.enabled:
            print("Ollama provider not available or disabled")
            return
        print("\nTesting Ollama provider...")
        # Use a simple prompt that expects JSON
        prompt = '"{\"view\": \"long\", \"confidence\": 0.8, \"reason\": \"test\"}"'  # Actually we need to ask for JSON
        # Better: ask the model to output JSON directly.
        prompt = "Respond with a JSON object: {\"view\": \"long\", \"confidence\": 0.8, \"reason\": \"test\"}"
        start = time.time()
        try:
            result = await service._call_ai_provider(ollama_provider, prompt)
            elapsed = time.time() - start
            print(f"Ollama response (took {elapsed:.2f}s):")
            print(result)
            if result:
                print("Parsed successfully.")
                if isinstance(result, dict):
                    print("Keys:", list(result.keys()))
                    # Check if it has the expected fields
                    if "view" in result and "confidence" in result and "reason" in result:
                        print("Contains required AI analysis fields.")
                    else:
                        print("Missing some required fields.")
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
