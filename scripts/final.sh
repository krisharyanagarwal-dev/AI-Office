set -u
R=/Users/a/trading/openalice-fleet
for i in $(seq 1 40); do [ -d "$R/.git" ] && [ -d "$R/office-hud/server" ] && break; sleep 8; done
cd "$R" || exit 1
export PATH="$HOME/.nvm/versions/node/v22.22.3/bin:$PATH"
echo "=== PRIORITY 1: what is actually true now ==="
printf "  inline gate removed from index.js : %s (0 = yes)\n" "$(grep -c 'function isLocalRequest' office-hud/server/index.js)"
printf "  imports the module                : %s\n" "$(grep -c "require('./lib/local_only')" office-hud/server/index.js)"
printf "  module file present               : %s\n" "$([ -f office-hud/server/lib/local_only.js ] && echo yes || echo no)"
printf "  regression test present           : %s\n" "$([ -f office-hud/server/test/mutating-routes.test.js ] && echo yes || echo no)"
echo "  -- tests --"
node --test office-hud/server/lib/local_only.test.js 2>&1|grep -E "^# (pass|fail)"|sed 's/^/    local_only      /'
node --test office-hud/server/localonly.test.js 2>&1|grep -E "^# (pass|fail)"|sed 's/^/    localonly       /'
node --test office-hud/server/test/mutating-routes.test.js 2>&1|grep -E "^# (pass|fail)"|sed 's/^/    mutating-routes /'
echo "  -- live probe --"
for ep in api/recovery/start api/recovery/stop api/autonomy/policy api/jarvis/command; do
  printf "    remote POST /%-20s -> " "$ep"
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 15 -X POST "https://as-mac-mini.tailff2dd7.ts.net/$ep" -H 'Content-Type: application/json' -d '{}'
done
printf "    local  POST /api/recovery/start -> %s\n" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST http://127.0.0.1:4747/api/recovery/start -H 'Content-Type: application/json' -d '{}')"
curl -s -o /dev/null --max-time 20 -X POST http://127.0.0.1:4747/api/recovery/stop -H 'Content-Type: application/json' -d '{}'
echo "  -- durability --"
echo "    commit ready to merge: $(git log --oneline -1 security/gate-structural 2>/dev/null | cut -c1-9)"
echo "    on origin:             $(git ls-remote origin refs/heads/security/gate-structural 2>/dev/null | cut -c1-9)"
echo
echo "=== TRADING SAFETY (must be untouched) ==="
/Users/a/.venvs/openalice/bin/python -c "
import json
d=json.load(open('/Users/a/trading/paper-benchmark/verification-report.json'))
p=d['eth_paper_execution']
print('  overall=%s testnet=%s orders_submitted=%s live_orders_allowed=%s' % (d['overall'], d['testnet']['mode'], p['orders_submitted'], p['live_orders_allowed']))" 2>/dev/null || echo "  (unreadable)"
