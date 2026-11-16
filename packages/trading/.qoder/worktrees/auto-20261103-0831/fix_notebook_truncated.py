# Fix the notebook by closing the incomplete code cell and adding proper endings

notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

# Read all lines
with open(notebook_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Original file has {len(lines)} lines")

# Find where the incomplete code cell starts by looking for the "# Import profit attribution functions" line
import_line = -1
for i, line in enumerate(lines):
    if "# Import profit attribution functions" in line:
        import_line = i
        break

if import_line == -1:
    print("Could not find '# Import profit attribution functions' line")
    exit(1)

print(f"Found '# Import profit attribution functions' at line {import_line} (0-indexed)")

# Work backwards to find the start of the code cell
# We expect to find:
# Line import_line:         "        \"# Import profit attribution functions\\n\""
# Line import_line - 1:     "      \"source\": [\n"
# Line import_line - 2:     "      \"outputs\": [],\n"
# Line import_line - 3:     "      \"metadata\": {},\n"
# Line import_line - 4:     "      \"execution_count\": null,\n"
# Line import_line - 5:     "      \"cell_type\": \"code\",\n"
# Line import_line - 6:     "    {\n"   (opening brace of the code cell)

expected_pattern = [
    '        "# Import profit attribution functions\\n"',  # 8 spaces
    '      "source": [\n',                               # 6 spaces
    '      "outputs": [],\n',                            # 6 spaces
    '      "metadata": {},\n',                           # 6 spaces
    '      "execution_count": null,\n',                  # 6 spaces
    '      "cell_type": "code",\n',                      # 6 spaces
    "    {\n"                                            # 4 spaces
]

# Check if we have enough lines to work with
if import_line < 6:
    print("Not enough lines to work with")
    exit(1)

# Check the pattern backwards from the import line
all_match = True
for i, expected in enumerate(expected_pattern):
    line_idx = import_line - i  # Working backwards from import_line
    if line_idx < 0 or line_idx >= len(lines):
        print(f"Line {line_idx} is out of bounds")
        all_match = False
        break
    actual = lines[line_idx]  # DON'T strip() - compare exactly as-is
    if actual != expected:
        print(f"Line {line_idx} does not match expected:")
        print(f"  Expected: {repr(expected)}")
        print(f"  Got:      {repr(actual)}")
        all_match = False
        break

if not all_match:
    print("Pattern matching failed")
    exit(1)

# If we get here, the pattern matches
incomplete_code_start = import_line - 6  # The opening brace line
print(f"Found incomplete code cell start at line {incomplete_code_start} (0-indexed)")

# Verify the structure of the incomplete code cell
expected_lines = [
    '      "cell_type": "code",\n',                      # 6 spaces
    '      "execution_count": null,\n',                  # 6 spaces
    '      "metadata": {},\n',                           # 6 spaces
    '      "outputs": [],\n',                            # 6 spaces
    '      "source": [\n',                               # 6 spaces
    '        "# Import profit attribution functions\\n"'  # 8 spaces
]

# Check each expected line
for i, expected in enumerate(expected_lines):
    line_idx = incomplete_code_start + 1 + i  # +1 because we skip the opening brace
    if line_idx >= len(lines):
        print(f"Line {line_idx} is out of bounds")
        exit(1)
    actual = lines[line_idx]  # DON'T strip() - compare exactly as-is
    if actual != expected:
        print(f"Line {line_idx} does not match expected:")
        print(f"  Expected: {repr(expected)}")
        print(f"  Got:      {repr(actual)}")
        exit(1)

print("Verified incomplete code cell structure")

# Now we need to close the incomplete code cell properly
# After line incomplete_code_start + 1 + 5, we should add:
# "      ]\n"          (close the source array)
# "    }\n"            (close the code cell)
# "    ]\n            (close the cells array)
# "  }\n"              (close the notebook)

closing_lines = [
    "      ]\n",
    "    }\n",
    "    ]\n",
    "  }\n"
]

# Keep everything up to and including line incomplete_code_start + 1 + 5, then add the closing lines
# incomplete_code_start + 1 + 5 = incomplete_code_start + 6
new_lines = lines[:incomplete_code_start + 6] + closing_lines

# Write the fixed file
with open(notebook_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Fixed incomplete code cell and added proper closing")
print(f"Original lines: {len(lines)}, New lines: {len(new_lines)}")

# Quick validation
import json
try:
    with open(notebook_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"SUCCESS: Notebook is valid JSON with {len(data['cells'])} cells")
    # Print the last few cell types to verify
    if len(data['cells']) >= 3:
        print(f"Third-to-last cell type: {data['cells'][-3]['cell_type']}")
        print(f"Second-to-last cell type: {data['cells'][-2]['cell_type']}")
        print(f"Last cell type: {data['cells'][-1]['cell_type']}")
        
        # Verify the last few cells are what we expect
        if data['cells'][-3]['cell_type'] == 'markdown' and '8.5 Profit Attribution Analysis' in str(data['cells'][-3]['source']):
            print("  -> Confirmed: Profit Attribution Analysis markdown cell found")
        if data['cells'][-2]['cell_type'] == 'code' and '# Import profit attribution functions' in str(data['cells'][-2]['source']):
            print("  -> Confirmed: Import profit attribution functions code cell found")
        if data['cells'][-1]['cell_type'] == 'markdown' and 'Conclusion & Next Steps' in str(data['cells'][-1]['source']):
            print("  -> Confirmed: Conclusion & Next Steps markdown cell found")
            
except Exception as e:
    print(f"Validation failed: {e}")
    import traceback
    traceback.print_exc()