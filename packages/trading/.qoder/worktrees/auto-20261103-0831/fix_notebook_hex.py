# Fix the notebook by removing the incomplete cell and properly closing it

notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

# Read the file as binary to avoid any encoding issues
with open(notebook_path, 'rb') as f:
    data = f.read()

print(f"Original file size: {len(data)} bytes")

# Convert to text for easier manipulation, but we'll be careful
text = data.decode('utf-8')

# Find the pattern we want to fix
# We want to find: "... decisions.\n\"      ].    }\n,    {\n    ]\n  }\n"
# And replace it with: "... decisions.\n\"      ].    }\n    ]\n  }\n"

# Let's find the distinctive part
distinctive = 'inform capital allocation decisions.\n\"      ].    }\n'
pos = text.find(distinctive)

if pos == -1:
    print("Could not find distinctive pattern")
    # Try to find a slightly different pattern
    distinctive = 'capital allocation decisions.\n\"      ].    }\n'
    pos = text.find(distinctive)
    if pos == -1:
        print("Could not find distinctive pattern 2")
        exit(1)

print(f"Found distinctive pattern at position {pos}")

# The distinctive pattern ends with "    }\n"
# After that, we should have ",    {\n    ]\n  }\n" which we want to replace with "    ]\n  }\n"

# Find where the distinctive pattern ends
distinctive_end = pos + len(distinctive)

# Check what comes after the distinctive pattern
after_distinctive = text[distinctive_end:distinctive_end + 20]
print(f"After distinctive pattern: {repr(after_distinctive)}")

# We expect to see: ",    {\n    ]\n  }\n"
# We want to replace this with: "    ]\n  }\n"

# Find the start of the incorrect part
incorrect_start = distinctive_end
# The incorrect part should start with ",    {\n    ]\n  }\n"
incorrect_pattern = ",    {\n    ]\n  }\n"
correct_ending = "    ]\n  }\n"

# Check if the incorrect pattern is actually there
if text[incorrect_start:incorrect_start + len(incorrect_pattern)] == incorrect_pattern:
    print(f"Found incorrect pattern at position {incorrect_start}")
    
    # Replace the incorrect pattern with the correct ending
    # New text = text before incorrect start + correct ending
    new_text = text[:incorrect_start] + correct_ending
    
    print(f"Replaced {len(incorrect_pattern)} bytes with {len(correct_ending)} bytes")
    print(f"Original size: {len(text)} bytes, New size: {len(new_text)} bytes")
    
    # Write the fixed file
    with open(notebook_path, 'wb') as f:
        f.write(new_text.encode('utf-8'))
    
    print("File written successfully")
else:
    print("Incorrect pattern not found where expected")
    print(f"Expected: {repr(incorrect_pattern)}")
    print(f"Found: {repr(text[incorrect_start:incorrect_start + len(incorrect_pattern)])}")
    
    # Let's see what we actually have
    # Look for the pattern that should be there: we want to find where the cells array should close
    # Let's try a different approach: find where the notebook should end
    
    # Look for the final "  }\n" that should be at the end
    final_close = text.rfind('  }\n')
    if final_close != -1:
        print(f"Found final close at position {final_close}")
        # What comes before it should be the end of the cells array: "    ]\n"
        # What comes before that should be the end of the last cell
        # Let's check what's at position final_close - 5 (should be "    ]\n")
        if final_close >= 5 and text[final_close - 5:final_close] == '    ]\n':
            print("Found correct cells array end")
            # What comes before that should be the end of the last cell: "    }\n"
            if final_close >= 10 and text[final_close - 10:final_close - 5] == '    }\n':
                print("Found correct cell end")
                # This means the file is already correct!
                print("File appears to be already correct")
            else:
                print("Cell end is not correct - needs fixing")
        else:
            print("Cells array end is not correct")
    else:
        print("Could not find final close")