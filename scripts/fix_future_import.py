lines = open('/Users/a/trading/openalice-fleet/services/free_harness.py').readlines()
insert_at = None
for i, line in enumerate(lines):
    if line.strip() == '"""' and i > 0:
        insert_at = i + 1
        break
if insert_at:
    lines.insert(insert_at, 'from __future__ import annotations\n')
    open('/Users/a/trading/openalice-fleet/services/free_harness.py', 'w').writelines(lines)
    print('Inserted at line', insert_at + 1)
else:
    print('Could not find insertion point')