// The production regression guard for costs.json snapshot reversion.
//
// loadCosts() pulls EVERY agent into each process's costCache at require time.
// saveCosts() used to write that whole cache back on every recordCost, so a
// long-lived process re-applied its entire boot-time snapshot whenever it
// recorded anything, reverting every other agent to what it looked like when
// that process started.
//
// That is why atomic writes (17669a9) and an exclusive lock (7db3f97) both
// failed to stop the loss. Both were correct and both operated on the wrong
// data: merging a stale full snapshot is not a merge, it is a rollback.
//
// Production evidence before the fix, one three minute window:
//     worker-angela  1934 records lost
//     worker-dwight   204
//     worker-toby     183
//
// The key detail is that the stale process must stay ALIVE. A process spawned
// after the other writes reloads the file and has no stale state, which is why
// an earlier version of this test passed against the broken code.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFile, execFileSync } = require("child_process");

const COST_JS = path.resolve(__dirname, "..", "cost.js");
const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";

const SLEEP = `const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);`;

// Long-lived process: require the module (taking a snapshot), wait for the
// go file, then record for its own agent only.
const HOLDER = `
  const fs = require("fs");
  const c = require(__COST__);
  ${SLEEP}
  fs.writeFileSync(__READY__, "1");
  const go = __GO__;
  const deadline = Date.now() + 20000;
  while (!fs.existsSync(go) && Date.now() < deadline) sleep(25);
  for (let i = 0; i < 6; i++) c.recordCost("alpha", __MODEL__, "NVIDIA", { prompt_tokens: 100, completion_tokens: 50 });
`;

function once(hive, agent, n) {
  execFileSync(process.execPath, ["-e",
    `const c = require(${JSON.stringify(COST_JS)});`
    + `for (let i=0;i<${n};i++) c.recordCost(${JSON.stringify(agent)}, ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 100, completion_tokens: 50 });`
  ], { env: { ...process.env, OPENALICE_HIVE: hive }, stdio: "ignore" });
}

test("a live process holding a stale snapshot does not revert other agents", async () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-revert-"));
  const db = path.join(hive, "costs.json");
  const ready = path.join(hive, "ready");
  const go = path.join(hive, "go");
  fs.writeFileSync(db, JSON.stringify({
    alpha: { daily: 0, monthly: 0, records: [{ costUsd: 0.001 }] },
    beta:  { daily: 0, monthly: 0, records: [{ costUsd: 0.001 }] },
  }));

  const src = HOLDER
    .replace("__COST__", JSON.stringify(COST_JS))
    .replace("__READY__", JSON.stringify(ready))
    .replace("__GO__", JSON.stringify(go))
    .replace("__MODEL__", JSON.stringify(MODEL));

  const child = execFile(process.execPath, ["-e", src], {
    env: { ...process.env, OPENALICE_HIVE: hive },
  });
  const done = new Promise(res => child.on("exit", res));

  // Wait for the holder to take its snapshot (beta == 1 record).
  const deadline = Date.now() + 15000;
  while (!fs.existsSync(ready) && Date.now() < deadline) sleepSync();
  assert.ok(fs.existsSync(ready), "holder never took its snapshot");

  // Another process advances beta to 10 records.
  once(hive, "beta", 9);
  assert.strictEqual(JSON.parse(fs.readFileSync(db, "utf8")).beta.records.length, 10);

  // The holder records for alpha only. It must not touch beta.
  fs.writeFileSync(go, "1");
  await done;

  const d = JSON.parse(fs.readFileSync(db, "utf8"));
  console.log("    alpha=%d beta=%d (beta must still be 10)",
    d.alpha.records.length, d.beta.records.length);
  assert.strictEqual(d.beta.records.length, 10,
    "beta was reverted to " + d.beta.records.length + " records by a stale holder");
  assert.strictEqual(d.alpha.records.length, 7, "alpha should have its own 7");
  fs.rmSync(hive, { recursive: true, force: true });
});

test("the same holds across many other agents", async () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-revert2-"));
  const db = path.join(hive, "costs.json");
  const ready = path.join(hive, "ready");
  const go = path.join(hive, "go");
  const seed = { alpha: { daily: 0, monthly: 0, records: [{ costUsd: 0.001 }] } };
  for (let i = 0; i < 15; i++) seed["other-" + i] = { daily: 0, monthly: 0, records: [{ costUsd: 0.001 }] };
  fs.writeFileSync(db, JSON.stringify(seed));

  const src = HOLDER
    .replace("__COST__", JSON.stringify(COST_JS))
    .replace("__READY__", JSON.stringify(ready))
    .replace("__GO__", JSON.stringify(go))
    .replace("__MODEL__", JSON.stringify(MODEL));
  const child = execFile(process.execPath, ["-e", src], { env: { ...process.env, OPENALICE_HIVE: hive } });
  const done = new Promise(res => child.on("exit", res));

  const deadline = Date.now() + 15000;
  while (!fs.existsSync(ready) && Date.now() < deadline) sleepSync();

  for (let i = 0; i < 15; i++) once(hive, "other-" + i, 4);
  fs.writeFileSync(go, "1");
  await done;

  const d = JSON.parse(fs.readFileSync(db, "utf8"));
  const clobbered = Object.keys(d).filter(k => k !== "alpha" && (d[k].records || []).length !== 5);
  console.log("    clobbered=%d (expected 0)", clobbered.length);
  assert.deepStrictEqual(clobbered, [], "reverted agents: " + clobbered.join(", "));
  fs.rmSync(hive, { recursive: true, force: true });
});

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms || 25);
}
