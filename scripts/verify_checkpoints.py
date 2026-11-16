import json, os, sys, hashlib, datetime

base = '.'
expected_dataset_hash = '743efdef3f7860d580fcb11c4c8f42589bb328b7ab4584b9ab72f9803e7f8d1e'
expected_git_commit = '48070e9738174ee2fe297ef63d5757f5259596ff'

checkpoint_files = [f for f in os.listdir(base) if f.startswith('VOL_HOSTILE_') and f.endswith('.json')]
print(f"Found {len(checkpoint_files)} checkpoint files")

# Helper to compute sha256 of a file
def file_sha256(path):
    try:
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception as e:
        return f"ERROR: {e}"

all_good = True
issues = []

for cf in sorted(checkpoint_files):
    path = os.path.join(base, cf)
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        issues.append((cf, f"JSON parse error: {e}"))
        all_good = False
        continue

    # Basic fields
    checkpoint_name = data.get('checkpoint')
    if checkpoint_name is None:
        issues.append((cf, "Missing 'checkpoint' field"))
        all_good = False
    # timestamp
    timestamp = data.get('timestamp')
    if timestamp is None:
        issues.append((cf, "Missing 'timestamp' field"))
        all_good = False
    else:
        # try to parse as ISO format
        try:
            datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except Exception:
            issues.append((cf, f"Timestamp not valid ISO: {timestamp}"))
            all_good = False
    # data_hash
    data_hash = data.get('data_hash')
    if data_hash is None:
        issues.append((cf, "Missing 'data_hash' field"))
        all_good = False
    else:
        if len(data_hash) != 64 or not all(c in '0123456789abcdef' for c in data_hash):
            issues.append((cf, f"data_hash not 64-char hex: {data_hash}"))
            all_good = False
        elif data_hash != expected_dataset_hash:
            issues.append((cf, f"data_hash mismatch: expected {expected_dataset_hash}, got {data_hash}"))
            all_good = False
    # git_commit
    git_commit = data.get('git_commit')
    if git_commit is None:
        issues.append((cf, "Missing 'git_commit' field"))
        all_good = False
    else:
        # allow special value for phase0
        if cf == 'VOL_HOSTILE_00_FROZEN.json':
            if git_commit != 'Not a git repo or error':
                issues.append((cf, f"phase0 git_commit expected 'Not a git repo or error', got {git_commit}"))
                all_good = False
        else:
            if len(git_commit) != 40 or not all(c in '0123456789abcdef' for c in git_commit):
                issues.append((cf, f"git_commit not 40-char hex: {git_commit}"))
                all_good = False
            elif git_commit != expected_git_commit:
                issues.append((cf, f"git_commit mismatch: expected {expected_git_commit}, got {git_commit}"))
                all_good = False

    # Check for parameters if present (optional but if present should be dict)
    if 'parameters' in data:
        if not isinstance(data['parameters'], dict):
            issues.append((cf, "'parameters' field is not a dict"))
            all_good = False

    # Check for test_result if present
    if 'test_result' in data:
        if not isinstance(data['test_result'], dict):
            issues.append((cf, "'test_result' field is not a dict"))
            all_good = False
        else:
            # optionally check for conclusion inside test_result
            if 'conclusion' not in data['test_result']:
                issues.append((cf, "'test_result' missing 'conclusion'"))
                all_good = False

    # Check for conclusion at top level (some have it)
    if 'conclusion' in data:
        if not isinstance(data['conclusion'], str):
            issues.append((cf, "'conclusion' field is not a string"))
            all_good = False

    # Verify referenced file hashes where applicable
    # For each checkpoint type, we know certain fields
    # We'll just do a generic check: if there is a field ending with '_hash' and a corresponding '_file' field, verify.
    for key in list(data.keys()):
        if key.endswith('_hash') and isinstance(data[key], str):
            file_key = key.replace('_hash', '_file')
            if file_key in data and isinstance(data[file_key], str):
                file_path = data[file_key]
                # If path is not absolute, assume relative to base
                if not os.path.isabs(file_path):
                    file_path = os.path.join(base, file_path)
                if os.path.exists(file_path):
                    actual_hash = file_sha256(file_path)
                    if actual_hash != data[key]:
                        issues.append((cf, f"Hash mismatch for {file_key}: expected {data[key]}, got {actual_hash}"))
                        all_good = False
                else:
                    issues.append((cf, f"Referenced file not found: {file_path}"))
                    all_good = False

    # If we got here without issues, mark ok
    if not any(iss[0]==cf for iss in issues):
        print(f"{cf}: OK")
    else:
        print(f"{cf}: ISSUES")

print("\n=== Summary ===")
if issues:
    print(f"Found {len(issues)} issues:")
    for cf, msg in issues:
        print(f"  {cf}: {msg}")
else:
    print("All checkpoints passed basic validation.")

