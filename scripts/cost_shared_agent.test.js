// Is the merge at RECORD level or at AGENT level?
//
// saveCosts does:
//     disk = JSON.parse(readFileSync(costs.json))
//     for (const [k, v] of costCache) disk[k] = v;      <-- replaces the whole agent entry
//
// If a process records for an agentId that another process also records for,
// the second writer replaces the first writer's records list with its own,
// which may be shorter. That is a lost update at AGENT granularity, and none
// of the existing tests cover it because they all give each agent exactly one
// writer.
//
// Every existing test passes while production still loses records, so the gap
// has to be somewhere the tests do not look.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFile } = require("child_process");

const COST_JS = path.resolve(__dirname, "..", "cost.js");
const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";

function proc(hive, code) {
  return new Promise((res, rej) => {
    execFile(process.execPath, ["-e",
      `const c = require(${JSON.stringify(COST_JS)});${code}`
    ], { env: { ...process.env, OPENALICE_HIVE: hive } }, e => e ? rej(e) : res());
  });
}

const rec = (agent, n) =>
  `for (let i=0;i<${n};i++) c.recordCost(${JSON.stringify(agent)}, ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 100, completion_tokens: 50 });`;

test("two processes recording for the SAME agent both survive", async () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-shared-"));
  const AG = "shared-agent";
  // Process A writes 10 records, process B writes 10, for the same agentId.
  await proc(hive, rec(AG, 10));
  await proc(hive, rec(AG, 10));

  const d = JSON.parse(fs.readFileSync(path.join(hive, "costs.json"), "utf8"));
  const n = (d[AG].records || []).length;
  console.log("    records for %s: %d (expected 20 if both survived)", AG, n);
  assert.strictEqual(n, 20,
    "one writer's records for " + AG + " were discarded: " + n + " of 20");
  fs.rmSync(hive, { recursive: true, force: true });
});

test("interleaved writers for the same agent accumulate", async () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-shared2-"));
  const AG = "shared-agent";
  await Promise.all([proc(hive, rec(AG, 8)), proc(hive, rec(AG, 8)), proc(hive, rec(AG, 8))]);
  const d = JSON.parse(fs.readFileSync(path.join(hive, "costs.json"), "utf8"));
  const n = (d[AG].records || []).length;
  console.log("    records for %s: %d (expected 24)", AG, n);
  assert.strictEqual(n, 24, "expected 24 records across 3 writers, got " + n);
  fs.rmSync(hive, { recursive: true, force: true });
});

test("monthly accrues across processes writing the same agent", async () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-shared3-"));
  const AG = "shared-agent";
  await proc(hive, rec(AG, 5));
  const one = JSON.parse(fs.readFileSync(path.join(hive, "costs.json"), "utf8"))[AG].monthly;
  await proc(hive, rec(AG, 5));
  const two = JSON.parse(fs.readFileSync(path.join(hive, "costs.json"), "utf8"))[AG].monthly;
  console.log("    monthly after 5 then 10 records: %s -> %s (expected to grow)", one, two);
  assert.ok(two > one, "monthly did not grow: " + one + " -> " + two);
  fs.rmSync(hive, { recursive: true, force: true });
});
