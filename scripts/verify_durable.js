// Direct verification: can a stale writer shrink an agent after a reconcile?
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFile, execFileSync } = require("child_process");

const COST_JS = "/Users/a/trading/openalice-fleet/hive/lib/llm/cost.js";
const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";
const hive = fs.mkdtempSync(path.join(os.tmpdir(), "dur-"));
const db = path.join(hive, "costs.json");
const ready = path.join(hive, "ready");
const go = path.join(hive, "go");

const once = (code) => execFileSync(process.execPath, ["-e",
  `const c = require(${JSON.stringify(COST_JS)});${code}`
], { env: { ...process.env, OPENALICE_HIVE: hive }, stdio: "ignore" });

once(`c.recordCost("alpha", ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 100, completion_tokens: 50 });`);
once(`c.recordCost("beta", ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 100, completion_tokens: 50 });`);
console.log("  seeded alpha/beta");

// Long-lived holder: snapshot now, then wait.
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
let exited = false;
child.on("exit", () => { exited = true; });

const sleepSync = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
const dl = Date.now() + 10000;
while (!fs.existsSync(ready) && Date.now() < dl) sleepSync();
console.log("  holder ready:", fs.existsSync(ready));

// Reconcile behind the holder's back: beta gains 20 records.
const d = JSON.parse(fs.readFileSync(db, "utf8"));
d.beta.records = Array.from({ length: 22 }, (_, i) => ({
  agentId: "beta", model: "m", provider: "nvidia", costUsd: 0.1,
  taskId: "rec-" + i, timestamp: "2026-01-01T00:00:0" + (i % 10) + "Z",
}));
d.beta.monthly = 99;
fs.writeFileSync(db, JSON.stringify(d));
console.log("  reconciled beta to", JSON.parse(fs.readFileSync(db, "utf8")).beta.records.length, "records, monthly=99");

fs.writeFileSync(go, "1");
const dl2 = Date.now() + 15000;
while (!exited && Date.now() < dl2) sleepSync(100);
console.log("  holder exited:", exited);

const after = JSON.parse(fs.readFileSync(db, "utf8"));
console.log("  RESULT alpha=" + after.alpha.records.length + " beta=" + after.beta.records.length +
            " beta.monthly=" + after.beta.monthly);
console.log("  VERDICT: " + (after.beta.records.length >= 22 && after.beta.monthly >= 99
  ? "PASS - a stale writer did not shrink the reconciled agent"
  : "FAIL - the reconcile was undone by a stale writer"));
fs.rmSync(hive, { recursive: true, force: true });
process.exit(0);
