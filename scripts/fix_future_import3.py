lines = open('/Users/a/trading/openalice-fleet/services/free_harness.py').readlines()

# Remove any incorrectly placed 'from __future__ import annotations' inside the docstring
# (i.e., between the opening and closing '"""')
in_docstring = False
docstring_start = None
docstring_end = None
quote_count = 0
for i, line in enumerate(lines):
    if line.strip() == '"""':
        quote_count += 1
        if quote_count == 1:
            in_docstring = True
            docstring_start = i
        elif quote_count == 2:
            in_docstring = False
            docstring_end = i
            break

if docstring_start is not None and docstring_end is not None:
    # Remove any 'from __future__ import annotations' lines between docstring start and end
    to_remove = []
    for i in range(docstring_start + 1, docstring_end):
        if lines[i].strip() == 'from __future__ import annotations':
            to_remove.append(i)
    for i in reversed(to_remove):
        del lines[i]
    print(f'Removed {len(to_remove)} misplaced import(s) from docstring (lines {docstring_start}-{docstring_end})')
    
    # Recalculate docstring_end after removals
    # The closing """ is now at docstring_end - len(to_remove)
    actual_end = docstring_end - len(to_remove)
    
    # Check if already present after the docstring
    if actual_end + 1 < len(lines) and lines[actual_end + 1].strip() == 'from __future__ import annotations':
        print('Already present after docstring')
    else:
        lines.insert(actual_end + 1, 'from __future__ import annotations\n')
        print(f'Inserted at line {actual_end + 2}')
    
    open('/Users/a/trading/openalice-fleet/services/free_harness.py', 'w').writelines(lines)
else:
    print('Could not find docstring boundaries')