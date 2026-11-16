import pathlib

p = pathlib.Path("scripts/run_task_truth_summary.py")
s = p.read_text(encoding="utf-8")

anchor = '    ("independent_verifier", ["check_independent_verifier.py", "--lib-root", os.path.dirname(HERE)]),\n'
assert s.count(anchor) == 1, "anchor count = %d" % s.count(anchor)

addition = anchor + (
    '    # Whether the fleet can actually complete LLM work. Every other check here\n'
    '    # is structural: a missing provider credential is a finding, but a missing\n'
    '    # credential is not an outage when a fallback can serve the request, so a\n'
    '    # structurally clean fleet can still be doing nothing. This measures the\n'
    '    # executor outcome instead.\n'
    '    ("llm_success_rate", ["check_llm_success_rate.py", "--limit", "0"]),\n'
)

p.write_text(s.replace(anchor, addition, 1), encoding="utf-8")
print("  wired llm_success_rate into the truth summary CHECKS list")
