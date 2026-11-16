import pathlib

p = pathlib.Path("scripts/batch_health.py")
s = p.read_text(encoding="utf-8")

old = 'label = sys.argv[1] if len(sys.argv) > 1 else "?"\nbatch = [a for a in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if a]\n\n_, fix_ct = mod.fix_commit()'

new = (
    'label = sys.argv[1] if len(sys.argv) > 1 else "?"\n'
    'batch = [a for a in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if a]\n'
    '\n'
    '# The fix to validate against must be the one actually being deployed.\n'
    '# Hardcoding a default here meant a batch was checked against 17669a9 while\n'
    '# 71e6745 was being rolled out, and 52 pre-fix agents were reported HEALTHY.\n'
    'FIX = sys.argv[3] if len(sys.argv) > 3 else mod.FIX_REF\n'
    '_, fix_ct = mod.fix_commit(FIX)\n'
    'print("  [%s] validating against fix: %s" % (label, FIX[:8]))'
)

assert s.count(old) == 1, "anchor count = %d" % s.count(old)
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("  batch_health.py now takes the fix ref as argv[3]")
