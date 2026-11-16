# Fix the notebook by replacing the incomplete markdown cell with the correct content

notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

# Read all lines
with open(notebook_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Original file has {len(lines)} lines")

# Find where the incomplete markdown cell starts
# Based on our analysis, it starts at line 634 (0-indexed) with "    {"
# Let's verify this by looking for the performance analysis code cell end

# Find the end of the performance analysis code cell
# It should end with "    }," (cell end with comma indicating another cell follows)
perf_analysis_end = -1
for i, line in enumerate(lines):
    if line.strip() == '    },':
        perf_analysis_end = i
        break

if perf_analysis_end == -1:
    print("Could not find performance analysis code cell end")
    exit(1)

print(f"Found performance analysis code cell end at line {perf_analysis_end} (0-indexed)")

# The next line should be the start of the markdown cell
markdown_cell_start = perf_analysis_end + 1
if markdown_cell_start >= len(lines):
    print("Markdown cell start is out of bounds")
    exit(1)

# Verify that the markdown cell start is "    {"
if lines[markdown_cell_start].strip() != '{':
    print(f"Expected '{{' at line {markdown_cell_start}, but got: {repr(lines[markdown_cell_start])}")
    exit(1)

print(f"Found markdown cell start at line {markdown_cell_start} (0-indexed), which is line {markdown_cell_start + 1} (1-indexed)")

# The incomplete markdown cell consists of:
# Line markdown_cell_start: "    {"
# Line markdown_cell_start + 1: "    ]"   (WRONG - should be cell content)
# Line markdown_cell_start + 2: "  }"   (WRONG - this is notebook close)

# We want to replace lines [markdown_cell_start + 1 : markdown_cell_start + 2] 
# (which is just line markdown_cell_start + 1: "    ]") 
# with the correct markdown cell content

# But actually, let's think about this more carefully.
# The structure should be:
# Line markdown_cell_start: "    {"   (start of markdown cell)
# Then the markdown cell content
# Then "    ]"   (closing cells array)
# Then "  }"   (closing notebook)

# So we want to replace everything after line markdown_cell_start 
# with the correct markdown cell content followed by the proper closing

# Define the correct markdown cell content
markdown_cell_content = [
    "      \"cell_type\": \"markdown\",\n",
    "      \"metadata\": {},\n",
    "      \"source\": [\n",
    "        \"## 8.5 Profit Attribution Analysis\\n\",\n",
        "        \"\\n\",\n",
        "        \"Enhancing our performance analysis with profit attribution to understand what's driving returns.\\n\",\n",
        "        \"\\n\",\n",
        "        \"We'll use the new profit attribution functions to decompose performance by:\\n\",\n",
        "        \"\\n\",\n",
        "        \"- Factors (momentum, value, quality, etc.)\\n\",\n",
        "        \"\\n\",\n",
        "        \"- Market regimes (trend up, trend down, chop)\\n\",\n",
        "        \"\\n\",\n",
        "        \"- Models (in our ensemble)\\n\",\n",
        "        \"\\n\",\n",
        "        \"This helps identify sources of alpha and inform capital allocation.\\n\"\n",
    "      ]\n",
    "    ]\n",
    "  }\n"
]

# Replace everything after the markdown cell start with the correct content
# Keep line markdown_cell_start (the "    {"), replace everything after it
new_lines = lines[:markdown_cell_start + 1] + markdown_cell_content

# Write the fixed file
with open(notebook_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Replaced lines {markdown_cell_start + 1} to end with correct markdown cell content")
print(f"Original lines: {len(lines)}, New lines: {len(new_lines)}")

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