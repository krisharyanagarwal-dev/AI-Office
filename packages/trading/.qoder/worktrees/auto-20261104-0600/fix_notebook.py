import json

# Read the file as text to fix it
notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

with open(notebook_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find where the incomplete content starts
# Look for the start of the incomplete profit attribution cell
incomplete_start = content.find('## 8.5 Profit Attribution Analysis')

if incomplete_start == -1:
    print("Could not find incomplete content")
    exit(1)

# Truncate at the start of incomplete content
truncated_content = content[:incomplete_start]

# Now we need to properly close the last cell and the notebook
# Let's parse what we have as JSON up to a point, then manually fix

# Instead, let's find the last complete cell ending
# Look for the pattern that ends a cell: "]\n    }"
last_cell_end = truncated_content.rstrip().rfind(']\n    }')

if last_cell_end == -1:
    print("Could not find last cell end")
    exit(1)

# Truncate to include the last complete cell
truncated_content = truncated_content[:last_cell_end + 4]  # Include "]\n    }"

# Now add the proper notebook ending
notebook_ending = '\n  ]\n}'

fixed_content = truncated_content + notebook_ending

# Write the fixed content
with open(notebook_path, 'w', encoding='utf-8') as f:
    f.write(fixed_content)

print("Fixed notebook structure")