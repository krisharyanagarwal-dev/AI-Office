# Fix the notebook by removing the incorrect trailing content and properly closing it

notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

# Read all lines
with open(notebook_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Original file has {len(lines)} lines")

# Find where the incorrect content starts
# Based on our analysis, the incorrect content starts at line 651 (0-indexed 650)
# which is "    ["  (should not be there)

# Let's find the line that contains just "    [" (with possible whitespace)
incorrect_line_idx = -1
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == '[':
        # Check if this is the incorrect one by looking at context
        # The line before should be the end of a cell: "    }"
        # And the line after should be "    ]"
        if i > 0 and i < len(lines) - 1:
            prev_stripped = lines[i-1].strip()
            next_stripped = lines[i+1].strip()
            if prev_stripped == '}' and next_stripped == ']':
                incorrect_line_idx = i
                break

if incorrect_line_idx == -1:
    print("Could not find incorrect line with just '['")
    # Fallback: look for the pattern we know is wrong
    for i, line in enumerate(lines):
        if '    ]' in line and i > 640 and i < 660:  # Constrain to expected area
            # Check if the line before this is a closing brace without comma
            if i > 0:
                prev_line = lines[i-1].strip()
                if prev_line == '}':
                    # This looks like we have "}\n    ]" which means the "[" we want is likely at i+1
                    if i+1 < len(lines) and lines[i+1].strip() == '[':
                        incorrect_line_idx = i+1
                        break

if incorrect_line_idx == -1:
    print("Could not find incorrect content, trying alternative approach")
    # Look for the markdown cell end and then fix from there
    # Find the end of the markdown cell (should be "    }" without comma)
    for i in range(len(lines)-1, 0, -1):
        if lines[i].strip() == '}':
            # Check if this is the end of a cell by looking at what comes after
            if i+1 < len(lines):
                next_line = lines[i+1].strip()
                # If what comes after is not a comma, this is the last cell
                if next_line != ',':
                    # The incorrect content starts after this line
                    incorrect_line_idx = i+1
                    break

if incorrect_line_idx == -1:
    print("Still could not find incorrect content")
    exit(1)

print(f"Found incorrect content starting at line {incorrect_line_idx} (0-indexed), which is line {incorrect_line_idx + 1} (1-indexed)")
print(f"Content at that line: {repr(lines[incorrect_line_idx])}")

# Truncate to keep everything before the incorrect content
truncated_lines = lines[:incorrect_line_idx]

# Now we need to properly close the notebook
# The last thing we have should be the end of the markdown cell
# Let's verify what we're keeping ends with

truncated_content = ''.join(truncated_lines)
print(f"Last 100 chars of truncated content: {repr(truncated_content[-100:])}")

# The truncated content should end with the markdown cell
# Which should end with: "    }\n" (closing brace of the cell, no comma because it's the last cell)

# Now we need to close the cells array and the notebook object
proper_ending = '\n    ]\n  }\n'

# Write the fixed file
fixed_content = truncated_content + proper_ending

with open(notebook_path, 'w', encoding='utf-8') as f:
    f.write(fixed_content)

print(f"Fixed notebook. Truncated before incorrect content at line {incorrect_line_idx}.")
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