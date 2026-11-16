import pathlib

p = pathlib.Path("services/free_harness.py")
lines = p.read_text(encoding="utf-8").split("\n")

# Locate the def and its two-line body, then insert one line after them.
i = next(i for i, l in enumerate(lines)
         if l.strip().startswith("def _record_success"))
assert lines[i + 1].strip() == "if provider in _circuit_failures:", lines[i + 1]
assert lines[i + 2].strip() == "_circuit_failures[provider] = 0", lines[i + 2]

INSERT_AT = i + 3
INSERT = [
    "        # Clearing the counter is not enough. _check_circuit() consults",
    "        # _circuit_opened_at, so without this a provider that has started",
    "        # answering again is still skipped for the whole reset window --",
    "        # turning every recovery into a 60s outage. Latent while these two",
    "        # functions were dead code; it becomes real the moment the call",
    "        # sites in _call_model exist.",
    "        _circuit_opened_at.pop(provider, None)",
]
lines[INSERT_AT:INSERT_AT] = INSERT
p.write_text("\n".join(lines), encoding="utf-8")
print("  inserted the circuit close at line %d" % (INSERT_AT + 1))
