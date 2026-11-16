# Fix the notebook by removing the incorrect trailing content and properly closing it

notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

# Read all lines
with open(notebook_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Original file has {len(lines)} lines")

# Find where the markdown cell starts
markdown_start = -1
for i, line in enumerate(lines):
    if '## 8.5 Profit Attribution Analysis' in line:
        markdown_start = i
        break

if markdown_start == -1:
    print("Could not find markdown cell start")
    exit(1)

print(f"Found markdown cell start at line {markdown_start} (0-indexed), which is line {markdown_start + 1} (1-indexed)")

# Now find where the markdown cell ends
# It should end with a line that contains just "    }" (four spaces and closing brace)
# with no trailing comma (because it's the last cell)
markdown_end = -1
for i in range(len(lines)-1, markdown_start, -1):  # Search backwards from end
    stripped = lines[i].strip()
    if stripped == '}':
        # Check if this is the end of the markdown cell by verifying it's a cell ending
        # The line before should be the end of the source array: "      ]"
        if i > 0 and lines[i-1].strip() == ']':
            # And the line before that should end with a source array closing bracket
            if i > 1 and lines[i-2].strip().endswith(']'):
                markdown_end = i
                break

if markdown_end == -1:
    print("Could not find markdown cell end")
    # Fallback: look for the pattern we know from our analysis
    # The markdown cell should end around line 650 based on our earlier analysis
    # Let's check if line 650 is "    }"
    if len(lines) > 650 and lines[650].strip() == '}':
        markdown_end = 650
    else:
        # Try to find it by looking for where the incorrect content starts
        # The incorrect content starts with "    [" 
        for i in range(len(lines)):
            if lines[i].strip() == '[':
                # The line before this should be the end of the markdown cell if it's correct
                if i > 0 and lines[i-1].strip() == '}':
                    markdown_end = i-1
                    break

if markdown_end == -1:
    print("Still could not find markdown cell end")
    exit(1)

print(f"Found markdown cell end at line {markdown_end} (0-indexed), which is line {markdown_end + 1} (1-indexed)")

# Verify that the markdown cell end is correct (no trailing comma)
if markdown_end + 1 < len(lines):
    next_line = lines[markdown_end + 1].strip()
    if next_line == ',':
        print("Warning: Markdown cell end has trailing comma - this would mean it's not the last cell")
    else:
        print("Good: Markdown cell end has no trailing comma - it is correctly the last cell")

# Truncate to keep everything up to and including the markdown cell end
truncated_lines = lines[:markdown_end + 1]

# Now we need to properly close the notebook
# After the markdown cell (which is the last cell), we need to close the cells array and notebook
proper_ending = '\n    ]\n  }\n'

# Write the fixed file
fixed_content = ''.join(truncated_lines) + proper_ending

with open(notebook_path, 'w', encoding='utf-8') as f:
    f.write(fixed_content)

print(f"Fixed notebook. Kept lines 0-{markdown_end} (markdown cell end), added proper ending.")
print(f"Original lines: {len(lines)}, New lines: {len(fixed_content.splitlines())}")

# Quick validation
try:
    with open(notebook_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"Successfully validated JSON. Number of cells: {len(data['cells'])}")
    # Print the last few cells to verify
    if len(data['cells']) >= 2:
        print(f"Second-to-last cell type: {data['cells'][-2]['cell_type']}")
        print(f"Last cell type: {data['cells'][-1]['cell_type']}")
        if data['cells'][-1]['cell_type'] == 'markdown':
            # Show first line of source to verify it's our markdown cell
            first_line = data['cells'][-1]['source'][0] if data['cells'][-1]['source'] else ''
            print(f'Last cell source starts with: {first_line[:50]}...')
except Exception as e:
    print(f"Validation failed: {e}")
    import traceback
    traceback.print_exc()