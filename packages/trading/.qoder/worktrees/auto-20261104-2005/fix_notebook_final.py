# Fix the notebook by correcting the ending after the markdown cell

notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

# Read all lines
with open(notebook_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Original file has {len(lines)} lines")

# Find the end of the markdown cell source array
# Look for the pattern: "      ]" followed by "    }," 
source_array_end = -1
for i in range(len(lines)-1):
    if lines[i].strip() == ']' and i+1 < len(lines) and lines[i+1].strip() == '},':
        source_array_end = i
        break

if source_array_end == -1:
    print("Could not find markdown cell source array end")
    exit(1)

print(f"Found source array end at line {source_array_end} (0-indexed)")

# The markdown cell end should be at source_array_end + 1
markdown_cell_end = source_array_end + 1
if markdown_cell_end >= len(lines):
    print("Markdown cell end is out of bounds")
    exit(1)

# Verify that line markdown_cell_end is "    },"
if lines[markdown_cell_end].strip() != '},':
    print(f"Expected '}},' at line {markdown_cell_end}, but got: {repr(lines[markdown_cell_end])}")
    exit(1)

print(f"Found markdown cell end at line {markdown_cell_end} (0-indexed), which is line {markdown_cell_end + 1} (1-indexed)")

# Fix 1: Change the markdown cell end from "    }," to "    }" (remove the comma since it's the last cell)
lines[markdown_cell_end] = lines[markdown_cell_end].replace('},', '}') + '\n'

# Fix 2: Replace everything after the markdown cell end with the proper closing
# Everything after line markdown_cell_end should be replaced with:
# "    ]\n  }\n"
new_closing = [
    "    ]\n",
    "  }\n"
]

# Keep everything up to and including the fixed markdown cell end, then add the new closing
new_lines = lines[:markdown_cell_end + 1] + new_closing

# Write the fixed file
with open(notebook_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Fixed markdown cell end and replaced closing")
print(f"Original lines: {len(lines)}, New lines: {len(new_lines)}")

# Quick validation
import json
try:
    with open(notebook_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"SUCCESS: Notebook is valid JSON with {len(data['cells'])} cells")
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