import pathlib
import re

p = pathlib.Path("services/free_harness.py")
src = p.read_text(encoding="utf-8")
lines = src.split("\n")

# Each entry: (regex to find the exact line, indent of that line, what to add).
# Anchored on the line's own leading whitespace so the inserted call lands at
# exactly the same depth as the statement it precedes. The previous attempt
# inserted before a log line at a different depth and broke the if/else.
TARGETS = [
    # --- success: tool_calls return ---
    (r'^\s+return _ModelResponse\(content=content or None, tool_calls=tool_ca',
     "success"),
    # --- success: plain content return ---
    (r'^\s+return content$',
     "success"),
    # --- 429 retries exhausted ---
    (r'^\s+log_structured\("warning", "retries_exhausted", provider=status\.na',
     "failure"),
    # --- 5xx retries exhausted (2nd occurrence of the same message) ---
    (r'^\s+log_structured\("warning", "retries_exhausted", provider=status\.na',
     "failure2"),
    # --- invalid request (400/404/413/422) ---
    (r'^\s+log_structured\("error", "non_retryable_error", provider=statu',
     "failure"),
    # --- other non-retryable with a key ---
    (r'^\s+log_structured\("error", "non_retryable_error", provider=statu',
     "failure2"),
    # --- non-NVIDIA / no key tracking ---
    (r'^\s+log_structured\("error", "non_retryable_error", provider=status\.na',
     "failure"),
    # --- timeout retries exhausted: the exact path the P0 took ---
    (r'^\s+log_structured\("warning", "timeout_retries_exhausted", provider=statu',
     "failure"),
    # --- generic exception, non-retryable ---
    (r'^\s+log_structured\("error", "non_retryable_error", provider=status\.name,',
     "failure"),
]

# Deduplicate: one match per (pattern, occurrence) in document order, and never
# let two entries target the same line.
used = set()
inserts = []  # (line_index, text_to_insert_above)

for pattern, kind in TARGETS:
    rx = re.compile(pattern)
    for i, l in enumerate(lines):
        if i in used or not rx.match(l):
            continue
        if any(i == j for j, _ in inserts):
            break
        indent = re.match(r'^(\s*)', l).group(1)
        call = ("_record_success" if kind.startswith("success")
                else "_record_failure")
        text = "%sself.%s(status.name)" % (indent, call)
        inserts.append((i, text))
        used.add(i)
        break

# Insert bottom-up so earlier indices stay valid.
for i, text in sorted(inserts, key=lambda x: -x[0]):
    lines[i:i] = [text]

p.write_text("\n".join(lines), encoding="utf-8")
print("  inserted %d accounting calls" % len(inserts))
for i, text in sorted(inserts):
    print("   line %5d  %s" % (i + 1, text.strip()))
