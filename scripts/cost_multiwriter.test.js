// Regression guard for the multi-writer clobber in costs.json.
//
// 57 agent processes each require lib/llm/cost.js. Every one loads costs.json
// into its own in-memory costCache at require time, and on each recordCost the
// old saveCosts() wrote the ENTIRE file from that cache. A process therefore
// rewrote the file to its own startup snapshot plus its own additions,
// reverting or deleting everything other processes had recorded since.
// Measured on the live fleet: F4 lost all 473 records in a 30s window.
//
// IMPORTANT: an earlier version of this test spawned a fresh process per
// recordCost, and it PASSED against the broken code. That was a false green.
// Every fresh process reloads the file, so its cache is never stale and the
// clobber never triggers. The defect only appears when a process that loaded
// the file earlier writes again after another process has changed it, so the
// test below keeps one process alive across another process's write using a
// file-based rendezvous.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync, spawn } = require("child_process");

const COST_JS = path.resolve(__dirname, "..", "cost.js");
const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";

function freshHive() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cost-mw-"));
}

function readIds(hive) {
  try {
    return Object.keys(JSON.parse(fs.readFileSync(path.join(hive, "costs.json"), "utf8")));
  } catch (e) {
    return [];
  }
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

// A long-lived process: loads the file, records, waits for the go file,
// records again, exits. Its in-memory cache is a snapshot from startup.
const LOOP_AGENT = `
  const fs = require("fs");
  const cost = require(${JSON.stringify(COST_JS)});
  cost.recordCost("alpha", ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 1000, completion_tokens: 10 });
  fs.writeFileSync(${JSON.stringify("%READY%")}, "1");
  const go = ${JSON.stringify("%GO%")};
  const deadline = Date.now() + 20000;
  while (!fs.existsSync(go) && Date.now() < deadline) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 25);
  cost.recordCost("alpha", ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 1000, completion_tokens: 10 });
`;

function runOnce(hive, agentId, tokens) {
  execFileSync(process.execPath, ["-e",
    `require(${JSON.stringify(COST_JS)}).recordCost(${JSON.stringify(agentId)}, ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: ${tokens}, completion_tokens: 10 });`
  ], { env: { ...process.env, OPENALICE_HIVE: hive }, stdio: "ignore" });
}

test("a long-lived process does not delete an agent another process added", async () => {
  const hive = freshHive();
  const ready = path.join(hive, "ready");
  const go = path.join(hive, "go");
  const src = LOOP_AGENT.replace(/%READY%/g, ready).replace(/%GO%/g, go);

  const child = spawn(process.execPath, ["-e", src], {
    env: { ...process.env, OPENALICE_HIVE: hive },
    stdio: "ignore",
  });

  // Wait for the long-lived process to take its startup snapshot.
  const deadline = Date.now() + 15000;
  while (!fs.existsSync(ready) && Date.now() < deadline) sleepSync(25);
  assert.ok(fs.existsSync(ready), "long-lived process never became ready");
  assert.deepStrictEqual(readIds(hive), ["alpha"]);

  // A different process records a brand new agent.
  runOnce(hive, "beta", 1000);
  assert.deepStrictEqual(readIds(hive).sort(), ["alpha", "beta"]);

  // Now the stale-snapshot process writes again. The old code reverts the file
  // to {alpha}, destroying beta.
  fs.writeFileSync(go, "1");
  const code = await new Promise((res) => child.on("exit", res));
  assert.strictEqual(code, 0, "long-lived process failed");

  const ids = readIds(hive).sort();
  assert.ok(ids.includes("beta"),
    "beta was erased by the stale-snapshot writer; surviving ids: " + JSON.stringify(ids));
  assert.ok(ids.includes("alpha"), "alpha missing");
  fs.rmSync(hive, { recursive: true, force: true });
});

test("records written by other processes survive many later writes", async () => {
  const hive = freshHive();
  const ready = path.join(hive, "ready");
  const go = path.join(hive, "go");
  const src = LOOP_AGENT.replace(/%READY%/g, ready).replace(/%GO%/g, go);

  const child = spawn(process.execPath, ["-e", src], {
    env: { ...process.env, OPENALICE_HIVE: hive },
    stdio: "ignore",
  });
  const deadline = Date.now() + 15000;
  while (!fs.existsSync(ready) && Date.now() < deadline) sleepSync(25);

  for (let i = 0; i < 5; i++) runOnce(hive, "other-" + i, 1000);
  assert.strictEqual(readIds(hive).length, 6, "all five others should exist before the stale write");

  fs.writeFileSync(go, "1");
  await new Promise((res) => child.on("exit", res));

  const ids = readIds(hive);
  for (let i = 0; i < 5; i++) {
    assert.ok(ids.includes("other-" + i), "other-" + i + " was destroyed; ids: " + JSON.stringify(ids));
  }
  fs.rmSync(hive, { recursive: true, force: true });
});

test("alpha's own records accumulate rather than being reset", async () => {
  const hive = freshHive();
  const ready = path.join(hive, "ready");
  const go = path.join(hive, "go");
  const src = LOOP_AGENT.replace(/%READY%/g, ready).replace(/%GO%/g, go);
  const child = spawn(process.execPath, ["-e", src], {
    env: { ...process.env, OPENALICE_HIVE: hive },
    stdio: "ignore",
  });
  const deadline = Date.now() + 15000;
  while (!fs.existsSync(ready) && Date.now() < deadline) sleepSync(25);
  fs.writeFileSync(go, "1");
  await new Promise((res) => child.on("exit", res));

  const raw = JSON.parse(fs.readFileSync(path.join(hive, "costs.json"), "utf8"));
  assert.strictEqual((raw.alpha.records || []).length, 2);
  assert.ok(Number.isFinite(raw.alpha.monthly), "monthly must be finite, got " + raw.alpha.monthly);
  fs.rmSync(hive, { recursive: true, force: true });
});
