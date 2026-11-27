#!/usr/bin/env python3
"""
Session Task Submitter - submit tasks to Qwen3.5-9B workers assigned to a session.

Usage:
  python3 session_task_submit.py <session_id> "<prompt>" [--worker worker-id]
  python3 session_task_submit.py <session_id> --file <prompt-file>
  python3 session_task_submit.py <session_id> --broadcast "<prompt>"

Reads session_registry.json to find workers assigned to the session.
Submits the prompt via Ollama /api/generate to the worker(s).
"""

from pathlib import Path
import json
import os
import sys
import time
import urllib.request
import urllib.error

REGISTRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_registry.json")
RESULT_DIR = str(Path.home() / ".openclaw" / "autonomous-qwen" / "results")

os.makedirs(RESULT_DIR, exist_ok=True)

SYSTEM_PROMPT = """You are a helpful assistant. Answer the user's question directly and concisely. Do not include thinking processes, analysis steps, or meta-commentary. Just provide the final answer."""


def load_registry():
    with open(REGISTRY) as f:
        return json.load(f)


def get_session_workers(reg, session_id):
    if session_id not in reg["sessions"]:
        return None
    s = reg["sessions"][session_id]
    workers = []
    for wid in s["workers"]:
        w = reg["workers"][wid]
        workers.append({"id": wid, "url": w["url"], "affinity": w.get("affinity", [])})
    return workers


def submit_to_worker(worker_url, prompt, task_id, timeout=300):
    """Submit a single prompt to a worker via Ollama API. Returns the response."""
    full_prompt = f"System: {SYSTEM_PROMPT}\n\nUser: {prompt}\n\nAssistant:"
    payload = json.dumps({
        "model": "hauhaucs/qwen3.5-9b-uncensored-aggressive",
        "prompt": full_prompt,
        "stream": False,
        "options": {"num_predict": 500, "temperature": 0.7},
    }).encode()

    req = urllib.request.Request(
        worker_url + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def save_result(task_id, worker_id, clean_answer, raw_response, prompt):
    result_file = os.path.join(RESULT_DIR, f"{task_id}.result")
    full_result = {
        "task_id": task_id,
        "worker": worker_id,
        "model": "hauhaucs/qwen3.5-9b-uncensored-aggressive",
        "raw_response": raw_response,
        "clean_answer": clean_answer,
        "prompt": prompt,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(result_file, "w") as f:
        json.dump(full_result, f, indent=2)
    return result_file


def extract_clean_answer(text):
    if not text:
        return text
    markers = [
        "\n\nFinal Answer:", "\n\nFinal answer:", "\n\nAnswer:",
        "\n\nResponse:", "\n\nResult:",
    ]
    for marker in markers:
        if marker in text:
            parts = text.split(marker, 1)
            if len(parts) == 2 and len(parts[1].strip()) > 0:
                return parts[1].strip()
    return text.strip()


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    session_id = sys.argv[1]

    # Parse remaining args
    prompt = None
    prompt_file = None
    broadcast = False
    target_worker = None

    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--worker" and i + 1 < len(sys.argv):
            target_worker = sys.argv[i + 1]
            i += 2
        elif arg == "--file" and i + 1 < len(sys.argv):
            prompt_file = sys.argv[i + 1]
            i += 2
        elif arg == "--broadcast":
            broadcast = True
            i += 1
        else:
            prompt = arg
            i += 1

    reg = load_registry()

    if prompt_file:
        with open(prompt_file) as f:
            prompt = f.read().strip()

    if not prompt:
        print("ERROR: No prompt provided")
        sys.exit(1)

    workers = get_session_workers(reg, session_id)
    if workers is None:
        print(f"ERROR: Session '{session_id}' not found. Spawn it first with:")
        print(f"  python3 session_worker_launcher.py spawn {session_id}")
        sys.exit(1)

    # Filter to target worker if specified
    if target_worker:
        workers = [w for w in workers if w["id"] == target_worker]
        if not workers:
            print(f"ERROR: Worker '{target_worker}' not found in session '{session_id}'")
            sys.exit(1)

    # If broadcast, submit to all workers; otherwise submit to first available
    targets = workers if broadcast else workers[:1]

    task_id = f"{session_id}-{int(time.time()*1000)}"
    print(f"Session '{session_id}' submitting task {task_id}")
    print(f"  Target workers: {[w['id'] for w in targets]}")
    print(f"  Prompt: {prompt[:80]}...")

    for w in targets:
        try:
            resp = submit_to_worker(w["url"], prompt, task_id)
            raw = resp.get("response", "N/A")
            clean = extract_clean_answer(raw)
            save_result(task_id, w["id"], clean, raw, prompt)
            print(f"  {w['id']} ({w['url']}): OK - {len(clean)} chars")
        except Exception as e:
            print(f"  {w['id']} ({w['url']}): FAILED - {e}")


if __name__ == "__main__":
    main()
