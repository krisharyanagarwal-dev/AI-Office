import sys

file_path = '/Users/a/trading/openalice-fleet/office-hud/server/index.js'
with open(file_path, 'r') as f:
    content = f.read()

insert_code = '''
// ---------- Alerts endpoints ----------
const { AlertEngine } = require('./lib/alerts');

let alertEngine = null;
function getAlertEngine() {
  if (!alertEngine) {
    alertEngine = new AlertEngine({
      read: () => ({ tasks: getTasks().tasks || [], agents: mergedAgents() }),
      intervalMs: 30000,
      config: {},
      onChange: (alerts) => {
        try {
          const { getLiveHub } = require('./lib/live_hub_ref');
          const hub = getLiveHub();
          if (hub) hub.publishAlerts(alerts);
        } catch {}
      },
    });
    alertEngine.start();
  }
  return alertEngine;
}

app.get('/api/alerts', (_req, res) => {
  const engine = getAlertEngine();
  res.json({ alerts: engine.snapshotList() });
});

app.post('/api/alerts/:fingerprint/ack', (req, res) => {
  const fingerprint = String(req.params.fingerprint || '');
  if (!fingerprint) {
    return res.status(400).json({ ok: false, error: { code: 'invalid_fingerprint', message: 'Fingerprint is required' } });
  }
  const engine = getAlertEngine();
  const acked = engine.ack(fingerprint);
  if (!acked) {
    return res.status(404).json({ ok: false, error: { code: 'alert_not_found', message: 'Alert not found', fingerprint } });
  }
  res.json({ ok: true, acknowledged: fingerprint });
});
'''

marker = "app.get('/api/verify'"
index = content.index(marker)
if index == -1:
    print('Marker not found')
    sys.exit(1)

new_content = content[:index] + insert_code + '\n' + content[index:]
with open(file_path, 'w') as f:
    f.write(new_content)
print('Inserted successfully')