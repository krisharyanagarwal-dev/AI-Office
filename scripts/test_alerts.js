async function main() {
  const { makeFixtureHive, loadServer, startTestServer } = require('./test/helpers/harness');
  const fixture = makeFixtureHive();
  const server = loadServer(fixture.hive);
  const http = await startTestServer(server.app);
  const r = await http.get('/api/alerts');
  console.log('status:', r.status);
  console.log('json:', JSON.stringify(r.json));
  const r2 = await http.post('/api/alerts/test-fingerprint/ack', {});
  console.log('ack status:', r2.status);
  await http.close();
  fixture.cleanup();
  process.exit(0);
}
main().catch(e => { console.error(e); process.exit(1); });