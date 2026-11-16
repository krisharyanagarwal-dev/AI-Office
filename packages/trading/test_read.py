import json

# Try to read the notebook
notebook_path = "/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb"

try:
    with open(notebook_path, 'r', encoding='utf-8') as f:
        notebook = json.load(f)
    print("Successfully read notebook")
    print(f"Number of cells: {len(notebook['cells'])}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()