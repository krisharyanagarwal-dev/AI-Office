import pathlib

p = pathlib.Path("scripts/check_stale_cost_writers.py")
s = p.read_text(encoding="utf-8")
if "--fix" in s and 'default=DEFAULT_FIX' in s:
    print("  already parameterised")
else:
    old = 'ap.add_argument("--fix", default=DEFAULT_FIX,\n                    help="commit that must be loaded; timestamp is read from git")'
    new = 'ap.add_argument("--fix", default=DEFAULT_FIX,\n                    help="commit that must be loaded; timestamp is read from git. "\n                         "Default is the merge fix; pass 17669a9 to also require "\n                         "the atomic-write fix.")'
    assert s.count(old) == 1, s.count(old)
    s = s.replace(old, new, 1)
    s = s.replace('DEFAULT_FIX = "f0d7912"', 'DEFAULT_FIX = "f0d7912"  # merge fix; use --fix 17669a9 for the atomic-write fix', 1)
    p.write_text(s, encoding="utf-8")
    print("  documented the --fix argument for the atomic-write target")
