const fs = require("fs");
const path = require("path");
const HIVE = "/Users/aryanagarwal/openalice-fleet/hive";
const file = path.join(HIVE, "terminals.json");

let jsonCache = new Map();

function readJsonCached(file, fallback) {
  let stat;
  try {
    stat = fs.statSync(file);
  } catch {
    jsonCache.delete(file);
    return fallback;
  }
  const cached = jsonCache.get(file);
  console.log("Cache check:", file, cached ? "hit" : "miss");
  if (cached && cached.mtimeMs === stat.mtimeMs && cached.size === stat.size) {
    console.log("Cache HIT - returning cached value");
    cached.at = Date.now();
    return cached.value;
  }
  console.log("Cache MISS - reading file");
  const value = JSON.parse(fs.readFileSync(file, "utf8"));
  jsonCache.set(file, { at: Date.now(), mtimeMs: stat.mtimeMs, size: stat.size, value });
  return value;
}

const result = readJsonCached(file, null);
console.log("Result shell_terminals:", result.shell_terminals.length);