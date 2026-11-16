import pathlib

p = pathlib.Path("services/free_harness.py")
lines = p.read_text(encoding="utf-8").split("\n")

i = next(i for i, l in enumerate(lines)
         if l.strip().startswith("def _record_success"))
# body is the two lines after the def
assert "_circuit_failures[provider] = 0" in lines[i + 2], lines[i + 2]

REPLACEMENT = [
    lines[i],
    lines[i + 1],
    "        _circuit_failures[provider] = 0",
    "        # Clearing the counter is not enough. _check_circuit() consults",
    "        # _circuit_opened_at, so without this a provider that starts",
    "        # answering again is still skipped for the whole reset window --",
    "        # turning a recovery into a 60s outage. Latent while these two",
    "        # functions were dead code; it becomes real the moment the call",
    "        # sites in _call_model exist.",
    "        _circuit_opened_at.pop(provider, None)",
]
lines[i:i + 3] = REPLACEMENT
p.write_text("\n".join(lines), encoding="utf-8")
print("  _record_success now closes the circuit, not just the counter")
