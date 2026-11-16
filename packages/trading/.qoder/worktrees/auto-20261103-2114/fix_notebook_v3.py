# Fix the notebook by truncating at the end of the last complete cell

notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

# Read all lines
with open(notebook_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find where the incomplete content starts
incomplete_line_idx = -1
for i, line in enumerate(lines):
    if line.strip() == '## 8.5 Profit Attribution Analysis':
        incomplete_line_idx = i
        break

if incomplete_line_idx == -1:
    print("Could not find incomplete content start")
    exit(1)

# The incomplete content starts at a markdown cell. We want to truncate 
# before this cell starts, at the end of the previous cell.
# Find the start of this incomplete cell (the opening brace)
incomplete_cell_start = -1
for i in range(incomplete_line_idx, -1, -1):
    if lines[i].strip() == '{':
        # Check if this looks like the start of a cell object
        # Look at the previous line to see if it's a comma separating cells
        if i > 0 and lines[i-1].strip() == ',':
            incomplete_cell_start = i
            break
        # Or if it's the first cell (unlikely in our case)
        elif i == 0:
            incomplete_cell_start = i
            break

if incomplete_cell_start == -1:
    print("Could not find start of incomplete cell")
    # Fallback: truncate at the line before the incomplete content
    incomplete_cell_start = incomplete_line_idx

# Truncate to keep everything before the incomplete cell
truncated_lines = lines[:incomplete_cell_start]

# Now we need to properly close the notebook
# Join the truncated lines and analyze the ending
truncated_content = ''.join(truncated_lines)

# The truncated content should end with the last complete cell
# We need to ensure it ends with a properly closed cell, then add the array and object closing

# Find where the last complete cell ends
# Look for the pattern that ends a cell: either "      ]    }," or "      ]\n    }"
last_cell_end = -1

# Pattern 1: Cell followed by another cell: "      ]    },"
pattern1 = '\n      ]    },'
pos1 = truncated_content.rfind(pattern1)
if pos1 != -1:
    last_cell_end = pos1 + len(pattern1) - 1  # Point to the closing brace of the cell
else:
    # Pattern 2: Last cell: "      ]\n    }"
    pattern2 = '\n      ]\n    }'
    pos2 = truncated_content.rfind(pattern2)
    if pos2 != -1:
        last_cell_end = pos2 + len(pattern2) - 1  # Point to the closing brace of the cell

if last_cell_end == -1:
    print("Warning: Could not find last cell end, using truncated content as-is")
    # We'll just use what we have and add proper closing
    pass
else:
    # Truncate to include the complete last cell
    chars_to_keep = last_cell_end + 1  # Include the character at last_cell_end
    truncated_content = truncated_content[:chars_to_keep]
    truncated_lines = [truncated_content]

# Now add the proper notebook ending: close the cells array and the notebook object
proper_ending = '\n    ]\n  }\n'

# Write the fixed file
fixed_content = ''.join(truncated_lines) + proper_ending

with open(notebook_path, 'w', encoding='utf-8') as f:
    f.write(fixed_content)

print(f"Fixed notebook. Truncated before incomplete cell at line {incomplete_line_idx}.")
print(f"Original lines: {len(lines)}, New lines: {len(fixed_content.splitlines())}")

# Quick validation
try:
    with open(notebook_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"Successfully validated JSON. Number of cells: {len(data['cells'])}")
except Exception as e:
    print(f"Validation failed: {e}")