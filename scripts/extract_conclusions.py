import json, os, sys

base = '.'
files = [f for f in os.listdir(base) if f.startswith('VOL_HOSTILE_') and f.endswith('.json') and not f.startswith('VOL_HOSTILE_COMPLETE')]
for f in sorted(files):
    path = os.path.join(base, f)
    try:
        with open(path, 'r') as fp:
            data = json.load(fp)
    except Exception as e:
        print(f"{f}: ERROR reading: {e}")
        continue
    conclusion = None
    if 'test_result' in data and isinstance(data['test_result'], dict):
        conclusion = data['test_result'].get('conclusion')
    if conclusion is None:
        conclusion = data.get('conclusion')
    print(f"{f}: {conclusion if conclusion is not None else 'NO CONCLUSION FOUND'}")
