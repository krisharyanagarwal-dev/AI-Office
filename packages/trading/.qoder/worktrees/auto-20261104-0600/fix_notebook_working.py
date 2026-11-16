# Fix the notebook by removing the incomplete code cell and properly closing it

notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

# Read all lines
with open(notebook_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find where the incomplete code cell starts
# Based on our analysis, it starts at line 635 (0-indexed would be 634)
# But let's find it dynamically to be safe
incomplete_cell_start = -1
for i, line in enumerate(lines):
    if '"cell_type": "code"' in line and i > 630 and i < 640:  # Constrain to expected area
        # Double-check this is the right one by looking at context
        if i+1 < len(lines) and '"execution_count": null' in lines[i+1]:
            incomplete_cell_start = i
            break

if incomplete_cell_start == -1:
    print("Could not find incomplete code cell start")
    # Fallback to known position
    incomplete_cell_start = 634  # 0-indexed line 635

print(f"Truncating at line {incomplete_cell_start} (0-indexed), which is line {incomplete_cell_start + 1} (1-indexed)")

# Truncate to keep everything before the incomplete cell
truncated_lines = lines[:incomplete_cell_start]

# Now we need to properly close the notebook
# The last thing we have should be the end of the previous cell
# Looking at our analysis, the last complete thing we have is:
# Line 634: "    },"  (the end of the markdown cell, with trailing comma)

# Join the truncated lines to work with the content
truncated_content = ''.join(truncated_lines)

# Remove the trailing comma from the last cell ending
# Find the last occurrence of "    }," at the end of content (after stripping whitespace)
stripped = truncated_content.rstrip()
if stripped.endswith('    },'):
    # Remove the trailing comma
    truncated_content = truncated_content[:len(truncated_content) - len(stripped) + len(stripped.rstrip('    },'))] + '    }'
    print("Removed trailing comma from last cell")
else:
    print("Warning: Could not find expected trailing comma pattern")

# Now close the cells array and the notebook object
proper_ending = '\n    ]\n  }\n'

# Write the fixed file
fixed_content = truncated_content + proper_ending

with open(notebook_path, 'w', encoding='utf-8') as f:
    f.write(fixed_content)

print(f"Fixed notebook. Truncated before incomplete code cell at line {incomplete_cell_start}.")
print(f"Original lines: {len(lines)}, New lines: {len(fixed_content.splitlines())}")

# Quick validation
try:
    with open(notebook_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"Successfully validated JSON. Number of cells: {len(data['cells'])}")
    # Print the last few cells to verify
    if len(data['cells']) >= 1:
        print(f"Last cell type: {data['cells'][-1]['cell_type']}")
        if data['cells'][-1]['cell_type'] == 'markdown':
            # Show first line of source to verify it's our markdown cell
            first_line = data['cells'][-1]['source'][0] if data['cells'][-1]['source'] else ''
            print(f"Last cell source starts with: {first_line[:50]}...")
except Exception as e:
    print(f"Validation failed: {e}")
    import traceback
    traceback.print_exc()