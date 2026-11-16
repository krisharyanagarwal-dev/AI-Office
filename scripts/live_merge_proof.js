// Live proof: a long-lived process writes again AFTER the file changed,
// exactly as a running agent does. Against the old writer this deleted the
// other agent; against the new one it must not.
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const COST_JS = "/Users/a/trading/openalice-fleet/hive/lib/llm/cost.js";
const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";

const hive = fs.mkdtempSync(path.join(os.tmpdir(), "live-"));
const DB = path.join(hive, "costs.json");

// cost.js reads OPENALICE_HIVE at require time, so it must be set first.
process.env.OPENALICE_HIVE = hive;

function once(id, tok) {
  execFileSync(process.execPath, ["-e",
    `require(${JSON.stringify(COST_JS)}).recordCost(${JSON.stringify(id)}, ${JSON.stringify(MODEL)}, "NVIDIA", { prompt_tokens: ${tok}, completion_tokens: 10 });`
  ], { env: { ...process.env, OPENALICE_HIVE: hive }, stdio: "ignore" });
}

const ids = () => Object.keys(JSON.parse(fs.readFileSync(DB, "utf8"))).sort();

// Process A loads the file now and holds a snapshot.
const cost = require(COST_JS);
cost.recordCost("floor-A", MODEL, "NVIDIA", { prompt_tokens: 1000, completion_tokens: 10 });
console.log("  A wrote floor-A        -> ids:", ids().join(","));

once("floor-B", 1000);
once("floor-C", 1000);
once("floor-D", 1000);
console.log("  B, C, D wrote          -> ids:", ids().join(","));

// A writes again from its stale in-memory cache.
cost.recordCost("floor-A", MODEL, "NVIDIA", { prompt_tokens: 1000, completion_tokens: 10 });
const after = ids();
console.log("  A wrote again (stale)  -> ids:", after.join(","));
console.log("");
console.log("  B/C/D survived         :", ["floor-B", "floor-C", "floor-D"].every(x => after.includes(x)) ? "YES" : "NO -- data destroyed");
const raw = JSON.parse(fs.readFileSync(DB, "utf8"));
console.log("  floor-A record count   :", (raw["floor-A"].records || []).length, "(expect 2)");
console.log("  floor-A monthly finite :", Number.isFinite(raw["floor-A"].monthly));
fs.rmSync(hive, { recursive: true, force: true });
