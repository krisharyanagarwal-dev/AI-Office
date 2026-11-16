// Demonstrates the failure mode in saveCosts() as currently written.
//
//   let disk = {};
//   try { disk = JSON.parse(readFileSync(COST_DB_PATH)) || {}; } catch (e) {}
//   for (const [k, v] of costCache) disk[k] = v;
//   writeFileSync(COST_DB_PATH, JSON.stringify(disk));
//
// writeFileSync is not atomic: it truncates then writes. A concurrent reader
// can therefore observe a half-written file, JSON.parse throws, the empty
// catch swallows it, disk stays {}, and the process writes ONLY its own
// cache. That is the whole-file clobber the merge was supposed to prevent.
//
// A corrupt or partially written costs.json is simulated directly, which is
// the same state a racing reader lands in. It does not need a race to
// reproduce: the code cannot tell "no data yet" from "could not parse".
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const COST_JS = "/Users/a/trading/openalice-fleet/hive/lib/llm/cost.js";
const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";
const hive = fs.mkdtempSync(path.join(os.tmpdir(), "cost-corrupt-"));
const DB = path.join(hive, "costs.json");

// Three agents with real history.
fs.writeFileSync(DB, JSON.stringify({
  alpha: { daily: 1, monthly: 1, records: Array.from({ length: 400 }, (_, i) => ({ i, costUsd: 0.001 })) },
  beta:  { daily: 1, monthly: 1, records: Array.from({ length: 300 }, (_, i) => ({ i, costUsd: 0.001 })) },
  gamma: { daily: 1, monthly: 1, records: Array.from({ length: 200 }, (_, i) => ({ i, costUsd: 0.001 })) },
}, null, 2));
console.log("  before: agents=%d records=%d", ...Object.values(
  (d => [Object.keys(d).length, Object.values(d).reduce((a, v) => a + v.records.length, 0)])(JSON.parse(fs.readFileSync(DB, "utf8")))));

// The file is observed half-written, exactly what a racing reader sees.
fs.writeFileSync(DB, '{"alpha": {"daily": 1, "monthly": 1, "reco');

execFileSync(process.execPath, ["-e",
  `require(${JSON.stringify(COST_JS)}).recordCost("alpha", ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: 10, completion_tokens: 10 });`
], { env: { ...process.env, OPENALICE_HIVE: hive }, stdio: "ignore" });

const after = JSON.parse(fs.readFileSync(DB, "utf8"));
const ids = Object.keys(after);
const recs = Object.values(after).reduce((a, v) => a + (v.records || []).length, 0);
console.log("  after : agents=%d records=%d  ids=%s", ids.length, recs, ids.join(","));
console.log("");
if (ids.length <= 1) {
  console.log("  CONFIRMED: a parse failure silently reduced the database to the one");
  console.log("  writing process. beta and gamma were erased by a writer that never");
  console.log("  saw them. The empty catch is the cause, not the merge.");
} else {
  console.log("  not reproduced: other agents survived");
}
fs.rmSync(hive, { recursive: true, force: true });
