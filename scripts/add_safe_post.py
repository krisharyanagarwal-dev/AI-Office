file_path = '/Users/a/trading/openalice-fleet/office-hud/server/index.js'
with open(file_path, 'r') as f:
    content = f.read()

old = "  '/api/fixer/chat',"
new = "  '/api/fixer/chat',\n  '/api/alerts/:fingerprint/ack',"

if new not in content:
    content = content.replace(old, new)
    with open(file_path, 'w') as f:
        f.write(content)
    print('Added to SAFE_POST')
else:
    print('Already in SAFE_POST')