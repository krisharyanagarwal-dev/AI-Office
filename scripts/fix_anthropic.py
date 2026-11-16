lines = open('/Users/a/trading/openalice-fleet/services/anthropic_bridge.py').readlines()

# Find the closing '"""' of the module docstring
quote_count = 0
insert_at = None
for i, line in enumerate(lines):
    if line.strip() == '"""':
        quote_count += 1
        if quote_count == 2:
            insert_at = i + 1
            break

if insert_at:
    # Check if already present
    if insert_at < len(lines) and lines[insert_at].strip() == 'from __future__ import annotations':
        print('Already present')
    else:
        lines.insert(insert_at, 'from __future__ import annotations\n')
        open('/Users/a/trading/openalice-fleet/services/anthropic_bridge.py', 'w').writelines(lines)
        print(f'Inserted at line {insert_at + 1}')
else:
    print('Could not find insertion point')