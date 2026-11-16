file_path = '/Users/a/trading/openalice-fleet/office-hud/server/index.js'
with open(file_path, 'r') as f:
    content = f.read()

# Remove /api/alerts/:fingerprint/ack from SAFE_POST (exact match won't work for parameterized URLs)
old_entry = "  '/api/alerts/:fingerprint/ack',\n"
if old_entry in content:
    content = content.replace(old_entry, '')
    print('Removed /api/alerts/:fingerprint/ack from SAFE_POST')
else:
    print('SAFE_POST entry not found (may already be removed)')

# Add alerts pattern to SAFE_POST_PATTERNS
old_patterns = '''const SAFE_POST_PATTERNS = [
  /^\\/api\\/sessions\\/[A-Za-z0-9_-]{1,128}\\/(reattach)$/,
  /^\\/api\\/messages\\/send$/,
];'''

new_patterns = '''const SAFE_POST_PATTERNS = [
  /^\\/api\\/alerts\\//,
  /^\\/api\\/sessions\\/[A-Za-z0-9_-]{1,128}\\/(reattach)$/,
  /^\\/api\\/messages\\/send$/,
];'''

if old_patterns in content:
    content = content.replace(old_patterns, new_patterns)
    print('Added alerts pattern to SAFE_POST_PATTERNS')
else:
    print('SAFE_POST_PATTERNS block not found')
    # Debug: show what's there
    import re
    match = re.search(r'const SAFE_POST_PATTERNS = \[.*?\];', content, re.DOTALL)
    if match:
        print('Found:', repr(match.group(0)[:200]))

with open(file_path, 'w') as f:
    f.write(content)
print('Done')