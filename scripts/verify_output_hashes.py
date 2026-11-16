import json, os, hashlib

base = '.'
checkpoint_files = [f for f in os.listdir(base) if f.startswith('VOL_HOSTILE_') and f.endswith('.json') and not f.startswith('VOL_HOSTILE_COMPLETE')]
print(f"Checking {len(checkpoint_files)} checkpoints for output hash mismatches")

mismatches = []
for cf in checkpoint_files:
    path = os.path.join(base, cf)
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading {cf}: {e}")
        continue
    output_file = data.get('output_file')
    output_hash = data.get('output_hash')
    if output_file and output_hash:
        # resolve path
        if not os.path.isabs(output_file):
            output_file = os.path.join(base, output_file)
        if os.path.exists(output_file):
            with open(output_file, 'rb') as f:
                actual_hash = hashlib.sha256(f.read()).hexdigest()
            if actual_hash != output_hash:
                mismatches.append((cf, output_file, output_hash, actual_hash))
        else:
            print(f"  {cf}: output file not found: {output_file}")

if mismatches:
    print("\nMismatches found:")
    for cf, ofile, expected, actual in mismatches:
        print(f"  {cf}:")
        print(f"    output_file: {ofile}")
        print(f"    expected hash: {expected}")
        print(f"    actual hash:   {actual}")
else:
    print("\nAll output hashes match.")
