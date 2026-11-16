import sys
sys.path.insert(0, '/Users/aryanagarwal/openalice-fleet')
from services.free_harness import get_nvidia_keys
import os
import requests
import json

keys = get_nvidia_keys()
print(f"Found {len(keys)} NVIDIA keys")
# Use first key for testing
api_key = keys[0] if keys else None
if not api_key:
    print("No NVIDIA key available")
    sys.exit(1)

url = "https://integrate.api.nvidia.com/v1/models"
headers = {"Authorization": f"Bearer {api_key}"}
try:
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code == 200:
        models = resp.json()
        print("Available models on NVIDIA endpoint:")
        for m in models.get('data', []):
            print(f"  {m.get('id')} owned_by: {m.get('owned_by', 'unknown')}")
    else:
        print(f"Failed to fetch models: {resp.status_code} {resp.text}")
except Exception as e:
    print(f"Error: {e}")

# Now test chat completions with model moonshotai/kimi-k3
chat_url = "https://integrate.api.nvidia.com/v1/chat/completions"
payload = {
    "model": "moonshotai/kimi-k3",
    "messages": [{"role": "user", "content": "Say exactly: KIMI_K3_OK"}],
    "max_tokens": 10,
    "temperature": 0.0,
    "stream": False
}
try:
    resp = requests.post(chat_url, headers=headers, json=payload, timeout=60)
    print(f"\nChat completion status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"Response: {json.dumps(data, indent=2)}")
    else:
        print(f"Error: {resp.text}")
except Exception as e:
    print(f"Exception: {e}")
