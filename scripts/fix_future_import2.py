lines = open('/Users/a/trading/openalice-fleet/services/free_harness.py').readlines()
# Find the SECOND '"""' on its own line (the closing docstring quote)
count = 0
insert_at = None
for i, line in enumerate(lines):
    if line.strip() == '"""':
        count += 1
        if count == 2:
            insert_at = i + 1
            break
if insert_at:
    # Check if already inserted
    if lines[insert_at - 1].strip() == 'from __future__ import annotations':
        print('Already present')
    else:
        lines.insert(insert_at, 'from __future__ import annotations\n')
        open('/Users/a/trading/openalice-fleet/services/free_harness.py', 'w').writelines(lines)
        print('Inserted at line', insert_at + 1)
else:
    print('Could not find insertion point')