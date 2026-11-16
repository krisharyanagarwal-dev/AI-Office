// Concurrency regression guard for the lost-update race in saveCosts().
//
// The atomic write in 17669a9 stopped torn reads: a reader never sees a
// half-written file, and an unparseable file is no longer collapsed to {}. It
// did NOT stop lost updates, because read-merge-write has no mutual exclusion.
// Two processes can both read the same base, and the second rename drops the
// first's records.
//
// Measured in production after the whole fleet was rolled onto 17669a9:
//   t= 90s  lost=570 across 6 agents (4.5% of the database)
//   t=100s  lost=134 across 7 agents (1.1% of the database)
// with no ids removed, which is the lost-update signature rather than a
// whole-database collapse.
//
// This spawns N processes that all record at the same instant and asserts
// that every record survives. Without the lock this fails.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFile, execFileSync } = require("child_process");

const COST_JS = path.resolve(__dirname, "..", "cost.js");
const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";

function record(hive, agentId, n) {
  execFileSync(process.execPath, ["-e",
    `const c = require(${JSON.stringify(COST_JS)});`
    + `for (let i = 0; i < ${n}; i++) c.recordCost(${JSON.stringify(agentId)}, ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 100, completion_tokens: 50 });`
  ], { env: { ...process.env, OPENALICE_HIVE: hive }, stdio: "ignore" });
}

function recordAsync(hive, agentId, n) {
  return new Promise((res, rej) => {
    execFile(process.execPath, ["-e",
      `const c = require(${JSON.stringify(COST_JS)});`
      + `for (let i = 0; i < ${n}; i++) c.recordCost(${JSON.stringify(agentId)}, ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 100, completion_tokens: 50 });`
    ], { env: { ...process.env, OPENALICE_HIVE: hive } }, (e) => e ? rej(e) : res());
  });
}

test("12 processes recording at once lose nothing", async () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-conc-"));
  const N = 12, PER = 5;
  // Barrier: every process waits until the same wall-clock instant, so their
  // read-merge-write windows genuinely overlap.
  const at = Date.now() + 1200;
  await Promise.all(Array.from({ length: N }, (_, i) => new Promise((res, rej) => {
    execFile(process.execPath, ["-e",
      `const c = require(${JSON.stringify(COST_JS)});`
      + `const spin = () => { const t = Date.now(); while (Date.now() < ${at}) {} };`
      + `spin(); for (let i = 0; i < ${PER}; i++) c.recordCost("conc-${i}", ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 100, completion_tokens: 50 });`
    ], { env: { ...process.env, OPENALICE_HIVE: hive } }, e => e ? rej(e) : res());
  })));

  const d = JSON.parse(fs.readFileSync(path.join(hive, "costs.json"), "utf8"));
  const ids = Object.keys(d);
  assert.strictEqual(ids.length, N,
    "expected all " + N + " agents, got " + ids.length + ": " + JSON.stringify(ids));
  for (const id of ids) {
    assert.strictEqual((d[id].records || []).length, PER,
      id + " has " + (d[id].records || []).length + " records, expected " + PER);
  }
  fs.rmSync(hive, { recursive: true, force: true });
});

test("no lock file or temp file is left behind", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-lock-"));
  record(hive, "solo", 3);
  const leftovers = fs.readdirSync(hive).filter(f => f !== "costs.json");
  assert.deepStrictEqual(leftovers, [], "stray files after a clean write: " + leftovers.join(", "));
  fs.rmSync(hive, { recursive: true, force: true });
});

test("a lock left behind by a dead writer does not wedge the database forever", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-stale-"));
  const db = path.join(hive, "costs.json");
  fs.writeFileSync(db, JSON.stringify({ keep: { daily: 1, monthly: 1, records: [{ costUsd: 0.001 }] } }));
  // A lock whose mtime is far in the past must be treated as abandoned.
  const lock = db + ".lock";
  fs.writeFileSync(lock, "999");
  const old = new Date(Date.now() - 120000);
  fs.utimesSync(lock, old, old);

  record(hive, "after-stale-lock", 2);

  const d = JSON.parse(fs.readFileSync(db, "utf8"));
  assert.ok(d.keep, "pre-existing agent was lost behind a stale lock");
  assert.ok(d["after-stale-lock"], "writer gave up instead of clearing a stale lock");
  assert.ok(!fs.existsSync(lock), "stale lock was not cleaned up");
  fs.rmSync(hive, { recursive: true, force: true });
});
