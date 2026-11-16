// Regression guard for the daily/monthly cost reset.
//
// resetDailyCosts used to do: for (const c of costCache.values()) c.daily = 0;
// saveCosts(). After dirty-agent tracking was added, saveCosts only merges the
// agents this process changed, and a reset marks none, so the reset wrote
// nothing at all. The daily figure would have silently kept accumulating
// across midnight and never reset.
//
// The obvious repair -- mark everything dirty and save -- is the one that
// reintroduces the original clobber, because it re-applies this process's
// boot-time snapshot for all 53 agents. So the reset has to act on the
// document on disk instead.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const COST_JS = path.resolve(__dirname, "..", "cost.js");
const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";

function run(hive, code) {
  execFileSync(process.execPath, ["-e",
    `const c = require(${JSON.stringify(COST_JS)});${code}`
  ], { env: { ...process.env, OPENALICE_HIVE: hive }, stdio: "ignore" });
}

const rec = (a, n) =>
  `for (let i=0;i<${n};i++) c.recordCost(${JSON.stringify(a)}, ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 1000, completion_tokens: 500 });`;

test("resetDailyCosts actually zeroes daily on disk", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-reset-"));
  run(hive, rec("alpha", 3));
  const db = path.join(hive, "costs.json");
  let d = JSON.parse(fs.readFileSync(db, "utf8"));
  assert.ok(d.alpha.daily > 0, "setup: daily should be positive, got " + d.alpha.daily);

  run(hive, "c.resetDailyCosts();");
  d = JSON.parse(fs.readFileSync(db, "utf8"));
  console.log("    daily after reset: %s", d.alpha.daily);
  assert.strictEqual(d.alpha.daily, 0, "daily was not reset on disk");
  fs.rmSync(hive, { recursive: true, force: true });
});

test("resetDailyCosts preserves every other agent's records", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-reset2-"));
  const db = path.join(hive, "costs.json");
  run(hive, rec("alpha", 4));
  run(hive, rec("beta", 4));
  run(hive, rec("gamma", 4));
  const before = JSON.parse(fs.readFileSync(db, "utf8"));
  assert.strictEqual(Object.keys(before).length, 3);

  run(hive, "c.resetDailyCosts();");
  const after = JSON.parse(fs.readFileSync(db, "utf8"));
  for (const k of ["alpha", "beta", "gamma"]) {
    assert.strictEqual(after[k].records.length, 4,
      k + " lost records during a daily reset");
  }
  assert.strictEqual(after.beta.daily, 0, "beta daily should be zeroed too");
  console.log("    all 3 agents kept 4 records, all dailies zeroed");
  fs.rmSync(hive, { recursive: true, force: true });
});

test("resetMonthlyCosts zeroes monthly and leaves daily alone", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-reset3-"));
  run(hive, rec("alpha", 3));
  const db = path.join(hive, "costs.json");
  const before = JSON.parse(fs.readFileSync(db, "utf8"));
  const dailyBefore = before.alpha.daily;

  run(hive, "c.resetMonthlyCosts();");
  const after = JSON.parse(fs.readFileSync(db, "utf8"));
  assert.strictEqual(after.alpha.monthly, 0, "monthly not reset");
  assert.strictEqual(after.alpha.daily, dailyBefore, "a monthly reset must not touch daily");
  assert.strictEqual(after.alpha.records.length, 3, "records were lost");
  fs.rmSync(hive, { recursive: true, force: true });
});

test("a reset leaves no lock or temp file behind", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-reset4-"));
  run(hive, rec("alpha", 2));
  run(hive, "c.resetDailyCosts();");
  const stray = fs.readdirSync(hive).filter(f => f !== "costs.json");
  assert.deepStrictEqual(stray, [], "stray files: " + stray.join(", "));
  fs.rmSync(hive, { recursive: true, force: true });
});
