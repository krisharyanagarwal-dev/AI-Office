file_path = '/Users/a/trading/openalice-fleet/office-hud/server/index.js'
with open(file_path, 'r') as f:
    content = f.read()

old_patterns = '''const SAFE_POST_PATTERNS = [
  /^\\/api\\/sessions\\/[A-Za-z0-9_-]{1,128}\\/reattach$/,
  /^\\/api\\/messages\\/send$/,
];'''

new_patterns = '''const SAFE_POST_PATTERNS = [
  /^\\/api\\/alerts\\//,
  /^\\/api\\/sessions\\/[A-Za-z0-9_-]{1,128}\\/reattach$/,
  /^\\/api\\/messages\\/send$/,
];'''

if old_patterns in content:
    content = content.replace(old_patterns, new_patterns)
    print('Added alerts pattern to SAFE_POST_PATTERNS')
else:
    print('Pattern not found')

with open(file_path, 'w') as f:
    f.write(content)
print('Done')