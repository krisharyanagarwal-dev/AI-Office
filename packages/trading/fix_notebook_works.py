# Fix the notebook by removing the incorrect trailing content and properly closing it

notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

# Read all lines
with open(notebook_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Original file has {len(lines)} lines")

# Find where the markdown cell ends
# Based on our analysis, it ends at line 640 (0-indexed) with "    }"
# Let's verify this by looking for the distinctive content we know is in the cell

# Find the line with the distinctive content
distinctive_line = -1
for i, line in enumerate(lines):
    if 'Enhancing our performance analysis with profit attribution to understand what\'s driving returns.' in line:
        distinctive_line = i
        break

if distinctive_line == -1:
    print("Could not find distinctive content")
    exit(1)

print(f"Found distinctive content at line {distinctive_line} (0-indexed)")

# Now find where the markdown cell ends
# It should end with a line that contains just "    }" (four spaces and closing brace)
# with no trailing comma (because it's the last cell)
markdown_end = -1
# Search backwards from the distinctive line to find the start of the cell, then forwards to find the end
# Or search forwards from distinctive line to find the end

# The cell ends with: "      ]" (end of source array) then "    }" (end of cell)
# Let's look for the "      ]" first
source_array_end = -1
for i in range(distinctive_line, len(lines)):
    if lines[i].strip() == ']':
        # Check if this is the end of a source array by looking at context
        # The line before should start with "      \"source\": ["
        # Actually, let's just look for the pattern we know
        if i > 0 and 'source' in lines[i-1]:
            source_array_end = i
            break

if source_array_end == -1:
    print("Could not find source array end")
    exit(1)

# The markdown cell should end two lines after the source array ends:
# Line i: "      ]"   (end of source array)
# Line i+1: "    }"   (end of cell)
markdown_end = source_array_end + 1

# Verify that this is indeed the end of the markdown cell
if markdown_end < len(lines):
    line_content = lines[markdown_end].strip()
    if line_content == '}':
        print(f"Found markdown cell end at line {markdown_end} (0-indexed), which is line {markdown_end + 1} (1-indexed)")
        print(f"Content: {repr(lines[markdown_end])}")
    else:
        print(f"Expected '}}' at line {markdown_end}, but got: {repr(lines[markdown_end])}")
        # Try to find the correct ending by searching backwards from distinctive line
        markdown_end = -1
        for i in range(len(lines)-1, distinctive_line-1, -1):
            if lines[i].strip() == '}':
                # Check if this looks like a cell ending
                if i > 0 and lines[i-1].strip() == ']':
                    markdown_end = i
                    break
        if markdown_end == -1:
            print("Still could not find markdown cell end")
            exit(1)
        else:
            print(f"Found markdown cell end at line {markdown_end} (0-indexed) via alternative search")
    # Verify it has no trailing comma (indicating it's the last cell)
    if markdown_end + 1 < len(lines):
        next_line = lines[markdown_end + 1].strip()
        if next_line == ',':
            print("Warning: Markdown cell end has trailing comma - this would mean it's not the last cell")
        else:
            print("Good: Markdown cell end has no trailing comma - it is correctly the last cell")
else:
    print("Markdown end index is out of bounds")
    exit(1)

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