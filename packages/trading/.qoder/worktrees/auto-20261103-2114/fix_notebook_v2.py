# Fix the notebook by removing incomplete content and properly closing it

notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

# Read all lines
with open(notebook_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line where incomplete content starts
# Look for the line that starts the incomplete profit attribution cell
incomplete_line_idx = -1
for i, line in enumerate(lines):
    if line.strip() == '## 8.5 Profit Attribution Analysis':
        incomplete_line_idx = i
        break

if incomplete_line_idx == -1:
    print("Could not find incomplete content start")
    exit(1)

# Truncate lines up to (but not including) the incomplete content
# We want to keep everything before line incomplete_line_idx
# But we need to make sure we end at a valid JSON structure

# The performance analysis code cell ends with a line that is just "      ]"
# Let's find the last occurrence of a line that ends a cell properly
# A cell ends with: "      ]    }," or just "      ]" if it's the last cell

# Actually, let's just truncate at incomplete_line_idx and then add proper closing
truncated_lines = lines[:incomplete_line_idx]

# Now we need to ensure the truncated content ends with a properly closed last cell
# Find the last cell ending in the truncated content
# We'll work backwards to find where the last complete cell ends

# Join the truncated lines to analyze
truncated_content = ''.join(truncated_lines)

# Find the last occurrence of a cell ending pattern
# A cell ends with: \n      ]    },\n  or for the last cell: \n      ]\n    }\n  ]
last_cell_end = -1

# Look for pattern: "      ]    }," (cell followed by another cell)
pattern1 = '\n      ]    },'
pos1 = truncated_content.rfind(pattern1)
if pos1 != -1:
    last_cell_end = pos1 + len(pattern1) - 1  # Point to the closing brace
else:
    # Look for pattern: "      ]\n    }" (last cell)
    pattern2 = '\n      ]\n    }'
    pos2 = truncated_content.rfind(pattern2)
    if pos2 != -1:
        last_cell_end = pos2 + len(pattern2) - 1  # Point to the closing brace

if last_cell_end == -1:
    print("Could not find last cell end in truncated content")
    # As fallback, let's just use the truncated lines and hope it's OK
    # But we'll add proper closing anyway
    pass
else:
    # Truncate to include the complete last cell
    # We want to keep everything up to and including the closing brace of the last cell
    # Then we'll close the cells array and notebook
    chars_to_keep = last_cell_end + 1  # Include the character at last_cell_end
    truncated_content = truncated_content[:chars_to_keep]
    truncated_lines = [truncated_content]  # We'll rebuild lines

# Now add the proper notebook ending
# We need to close the cells array and the notebook object
# If the last thing we have is a cell ending with }, we need to close the array and object
# The structure should end with: \n    ]\n  }\n

# Let's just add the standard ending
proper_ending = '\n    ]\n  }\n'

# Write the fixed file
fixed_content = ''.join(truncated_lines) + proper_ending

with open(notebook_path, 'w', encoding='utf-8') as f:
    f.write(fixed_content)

print(f"Fixed notebook. Truncated at line {incomplete_line_idx}, added proper ending.")
print(f"Original lines: {len(lines)}, New lines: {len(fixed_content.splitlines())}")