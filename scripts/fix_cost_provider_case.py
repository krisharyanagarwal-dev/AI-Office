import pathlib

# PRICING is keyed lowercase (nvidia, groq, openrouter, ...) but every agent
# manager forwards response.provider, which the LLM client sets uppercase
# ("NVIDIA"). The table lookup therefore always missed and fell through to the
# generic 0.0004/1k rate, halving the recorded price of every real call.
# Normalise the key instead of touching 59 call sites.
for name in ("lib/llm/cost.js", "lib/llm/cost.ts"):
    p = pathlib.Path(name)
    s = p.read_text(encoding="utf-8")
    old = "PRICING[provider]?.[model]"
    new = "PRICING[String(provider).toLowerCase()]?.[model]"
    assert s.count(old) == 1, "%s: anchor count = %d" % (name, s.count(old))
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    print("  %s: provider key normalised" % name)
