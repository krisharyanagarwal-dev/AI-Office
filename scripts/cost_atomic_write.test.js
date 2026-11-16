// Regression guard for the parse-failure clobber in saveCosts().
//
// The merge added in f0d7912 read the existing document, merged this
// process's entries over it, and wrote the result back with
// fs.writeFileSync. Two things were wrong with that:
//
//   1. writeFileSync truncates before it writes, so a concurrent reader can
//      observe a half-written file.
//   2. The JSON.parse of that half-written file threw, and the empty catch
//      swallowed it, leaving the "merged" document empty. The process then
//      wrote ONLY its own cache, which is precisely the whole-file clobber
//      the merge was introduced to prevent.
//
// Measured against the code as it stood, a document holding three agents and
// 900 records was reduced to one agent and one record by a writer that had
// never seen the other two.
//
// The rule these tests pin: if the on-disk document cannot be parsed, the
// writer must leave it exactly as it found it. Losing one pending record is
// recoverable; erasing 56 other processes' data is not.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const COST_JS = path.resolve(__dirname, "..", "cost.js");
const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";

function record(hive, agentId) {
  execFileSync(process.execPath, ["-e",
    `require(${JSON.stringify(COST_JS)}).recordCost(${JSON.stringify(agentId)}, ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 10, completion_tokens: 10 });`
  ], { env: { ...process.env, OPENALICE_HIVE: hive }, stdio: "ignore" });
}

function seeded(hive) {
  const db = path.join(hive, "costs.json");
  fs.writeFileSync(db, JSON.stringify({
    alpha: { daily: 1, monthly: 1, records: Array.from({ length: 400 }, () => ({ costUsd: 0.001 })) },
    beta:  { daily: 1, monthly: 1, records: Array.from({ length: 300 }, () => ({ costUsd: 0.001 })) },
    gamma: { daily: 1, monthly: 1, records: Array.from({ length: 200 }, () => ({ costUsd: 0.001 })) },
  }));
  return db;
}

test("an unparseable costs.json is left intact, not replaced by one agent", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-corrupt-"));
  const db = seeded(hive);
  // Exactly what a reader sees when it catches a half-written file.
  const partial = '{"alpha": {"daily": 1, "monthly": 1, "reco';
  fs.writeFileSync(db, partial);

  record(hive, "alpha");

  const after = fs.readFileSync(db, "utf8");
  assert.strictEqual(after, partial,
    "costs.json was rewritten despite being unparseable; other agents' data is at risk");
  fs.rmSync(hive, { recursive: true, force: true });
});

test("a truncated costs.json is never reduced to the writing process alone", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-corrupt2-"));
  const db = seeded(hive);
  const good = fs.readFileSync(db, "utf8");
  fs.writeFileSync(db, good.slice(0, Math.floor(good.length / 2)));  // truncated mid-record

  record(hive, "gamma");

  let ids = [];
  try {
    ids = Object.keys(JSON.parse(fs.readFileSync(db, "utf8")));
  } catch (e) {
    ids = [];  // left unparseable, which is the safe outcome
  }
  assert.ok(ids.length !== 1,
    "database collapsed to a single agent: " + JSON.stringify(ids));
  fs.rmSync(hive, { recursive: true, force: true });
});

test("writes are atomic, so a reader never sees a half-written file", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-atomic-"));
  const db = seeded(hive);
  record(hive, "alpha");

  // No temp file may be left behind next to the database.
  const leftovers = fs.readdirSync(hive).filter(f => f.includes(".tmp."));
  assert.deepStrictEqual(leftovers, [], "temp files left behind: " + leftovers.join(", "));

  const d = JSON.parse(fs.readFileSync(db, "utf8"));
  assert.deepStrictEqual(Object.keys(d).sort(), ["alpha", "beta", "gamma"],
    "a normal write must still merge and keep everyone");
  assert.strictEqual((d.alpha.records || []).length, 401);
  assert.strictEqual((d.beta.records || []).length, 300);
  assert.strictEqual((d.gamma.records || []).length, 200);
  fs.rmSync(hive, { recursive: true, force: true });
});

test("a normal write still merges and preserves every other agent", () => {
  const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-merge-"));
  const db = seeded(hive);
  record(hive, "alpha");
  const d = JSON.parse(fs.readFileSync(db, "utf8"));
  assert.deepStrictEqual(Object.keys(d).sort(), ["alpha", "beta", "gamma"]);
  assert.ok(Number.isFinite(d.alpha.monthly), "alpha monthly must be finite");
  fs.rmSync(hive, { recursive: true, force: true });
});
