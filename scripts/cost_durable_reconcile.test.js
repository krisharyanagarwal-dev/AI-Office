// The reconcile durability guard.
//
// A reconcile adds records to costs.json for agents whose processes hold an
// older in-memory cache. saveCosts then merged a dirty agent by REPLACING
// disk[k] with the process's own entry, so the first time that agent recorded
// again it silently undid the reconciliation. Observed twice: a 985 record
// reversion, then 356 and 33 in a later soak.
//
// The merge is now a union keyed on (timestamp, taskId), and the accumulators
// take the larger value, so a stale writer can never shrink an agent's history.
// Cost records are append-only, so never shrinking is the correct invariant.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFile, execFileSync } = require("child_process");

const COST_JS = path.resolve(__dirname, "..", "cost.js");
const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";

function once(hive, code) {
  execFileSync(process.execPath, ["-e",
    `const c = require(${JSON.stringify(COST_JS)});${code}`
  ], { env: { ...process.env, OPENALICE_HIVE: hive }, stdio: "ignore" });
}

const rec = (agent, n) =>
  `for (let i=0;i<${n};i++) c.recordCost(${JSON.stringify(agent)}, ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 100, completion_tokens: 50 });`;

const sleepSync = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

test("a stale writer cannot shrink an agent after a reconcile", async () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-durable-"));
  const db = path.join(hive, "costs.json");
  const ready = path.join(hive, "ready");
  const go = path.join(hive, "go");

  once(hive, rec("alpha", 2));
  once(hive, rec("beta", 2));

  // Long-lived process: takes its snapshot now, with beta at 2 records.
  const src = `
    const fs = require("fs");
    const c = require(${JSON.stringify(COST_JS)});
    const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
    fs.writeFileSync(${JSON.stringify(ready)}, "1");
    const go = ${JSON.stringify(go)};
    const dl = Date.now() + 20000;
    while (!fs.existsSync(go) && Date.now() < dl) sleep(25);
    c.recordCost("alpha", ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 100, completion_tokens: 50 });
  `;
  const child = execFile(process.execPath, ["-e", src], { env: { ...process.env, OPENALICE_HIVE: hive } });
  const done = new Promise(r => child.on("exit", r));

  const dl = Date.now() + 15000;
  while (!fs.existsSync(ready) && Date.now() < dl) sleepSync();
  assert.ok(fs.existsSync(ready), "holder never started");

  // A reconcile: beta gains 20 records behind the holder's back.
  const d = JSON.parse(fs.readFileSync(db, "utf8"));
  d.beta.records = Array.from({ length: 22 }, (_, i) => ({
    agentId: "beta", model: "m", provider: "nvidia", costUsd: 0.1,
    taskId: "reconciled-" + i, timestamp: "2026-01-01T00:00:0" + (i % 10) + "Z",
  }));
  d.beta.monthly = 99;
  fs.writeFileSync(db, JSON.stringify(d));
  assert.strictEqual(JSON.parse(fs.readFileSync(db, "utf8")).beta.records.length, 22);

  // The stale holder records for alpha only.
  fs.writeFileSync(go, "1");
  await done;

  const after = JSON.parse(fs.readFileSync(db, "utf8"));
  console.log("    alpha=%d beta=%d (beta must stay >= 22)",
    after.alpha.records.length, after.beta.records.length);
  assert.ok(after.beta.records.length >= 22,
    "reconcile was undone: beta fell to " + after.beta.records.length);
  assert.strictEqual(after.beta.monthly, 99, "a larger archive monthly was overwritten");
  fs.rmSync(hive, { recursive: true, force: true });
});

test("the union does not duplicate a record present in both", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-durable2-"));
  once(hive, rec("gamma", 4));
  const db = path.join(hive, "costs.json");
  const before = JSON.parse(fs.readFileSync(db, "utf8")).gamma.records.length;
  // A second process with the same records, writing again.
  once(hive, rec("gamma", 1));
  const after = JSON.parse(fs.readFileSync(db, "utf8")).gamma.records.length;
  console.log("    gamma %d -> %d (must be exactly +1)", before, after);
  assert.strictEqual(after, before + 1, "union duplicated or dropped records");
  fs.rmSync(hive, { recursive: true, force: true });
});

test("daily and monthly never regress", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-durable3-"));
  const db = path.join(hive, "costs.json");
  once(hive, rec("delta", 3));
  const first = JSON.parse(fs.readFileSync(db, "utf8")).delta;
  // Force a much larger accumulator on disk, as a reconcile would.
  const d = JSON.parse(fs.readFileSync(db, "utf8"));
  d.delta.monthly = 500;
  d.delta.daily = 400;
  fs.writeFileSync(db, JSON.stringify(d));
  once(hive, rec("delta", 1));
  const after = JSON.parse(fs.readFileSync(db, "utf8")).delta;
  console.log("    monthly %s -> %s (must not fall below 500)", first.monthly, after.monthly);
  assert.ok(after.monthly >= 500, "monthly regressed to " + after.monthly);
  assert.ok(after.daily >= 400, "daily regressed to " + after.daily);
  fs.rmSync(hive, { recursive: true, force: true });
});
