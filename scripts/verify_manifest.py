import json, os, hashlib

manifest_path = 'VOL_HOSTILE_COMPLETE.json'
with open(manifest_path, 'r') as f:
    manifest = json.load(f)

print("Manifest loaded.")

# Verify dataset hash
expected_dataset_hash = '743efdef3f7860d580fcb11c4c8f42589bb328b7ab4584b9ab72f9803e7f8d1e'
if manifest.get('dataset_hash') != expected_dataset_hash:
    print(f"ERROR: dataset_hash mismatch: manifest {manifest.get('dataset_hash')} vs expected {expected_dataset_hash}")
else:
    print("dataset_hash OK")

# Verify final_git_commit
expected_git_commit = '48070e9738174ee2fe297ef63d5757f5259596ff'
if manifest.get('final_git_commit') != expected_git_commit:
    print(f"ERROR: final_git_commit mismatch: manifest {manifest.get('final_git_commit')} vs expected {expected_git_commit}")
else:
    print("final_git_commit OK")

# Verify test_status (just record)
test_status = manifest.get('test_status')
print(f"test_status: {test_status}")

# Verify final_evidence_classification
classification = manifest.get('final_evidence_classification')
allowed = ['ROBUST', 'PARTIALLY_SUPPORTED', 'FRAGILE', 'NOT_SUPPORTED', 'INCONCLUSIVE']
if classification not in allowed:
    print(f"ERROR: final_evidence_classification invalid: {classification}")
else:
    print(f"final_evidence_classification: {classification}")

# Verify flags
print(f"research_only: {manifest.get('research_only')}")
print(f"live_trading_modified: {manifest.get('live_trading_modified')}")
print(f"production_files_modified: {manifest.get('production_files_modified')}")

# Verify completion_timestamp (just check format)
import datetime
ts = manifest.get('completion_timestamp')
try:
    datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
    print("completion_timestamp format OK")
except Exception as e:
    print(f"WARNING: completion_timestamp format issue: {e}")

# Verify checkpoint hashes
print("\nVerifying checkpoint hashes:")
all_good = True
for rel_path, info in manifest.get('checkpoints', {}).items():
    expected_hash = info.get('sha256')
    # resolve path relative to manifest directory
    file_path = os.path.join(os.path.dirname(manifest_path), rel_path)
    if not os.path.exists(file_path):
        print(f"  {rel_path}: FILE NOT FOUND")
        all_good = False
        continue
    with open(file_path, 'rb') as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()
    if actual_hash != expected_hash:
        print(f"  {rel_path}: HASH MISMATCH (expected {expected_hash}, got {actual_hash})")
        all_good = False
    else:
        print(f"  {rel_path}: OK")

if all_good:
    print("\nAll checkpoint hashes match manifest.")
else:
    print("\nSome checkpoint hashes mismatched.")

