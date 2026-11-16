const c = require("/Users/a/trading/openalice-fleet/hive/lib/llm/cost.js");
const M = "nvidia/nemotron-3-ultra-550b-a55b";
for (const p of ["nvidia", "NVIDIA"]) {
  c.recordCost("C2-" + p, M, p, { prompt_tokens: 1000, completion_tokens: 1000 });
  console.log("  provider=" + p.padEnd(8) + " -> " +
    c.getAgentCosts("C2-" + p).records[0].costUsd + "  (expect 0.0016 for both)");
}
