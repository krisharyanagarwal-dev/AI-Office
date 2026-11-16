// Regression guard for the cost-usage schema mismatch.
//
// Every agent manager calls recordCost(..., response.usage) with the raw
// provider payload, which is snake_case: { prompt_tokens, completion_tokens }.
// cost.js read usage.promptTokens / usage.completionTokens, so every lookup
// was undefined, `undefined * price` produced NaN, and JSON.stringify turned
// that into null on disk. All 8 agentIds in costs.json carried costUsd:null
// and monthly:null as a result.
//
// This exercises only the public exports, and runs against a temporary
// OPENALICE_HIVE so it never reads or writes the real costs.json.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cost-test-"));
process.env.OPENALICE_HIVE = tmp;

// cost.js reads OPENALICE_HIVE at require time to build COST_DB_PATH, so
// pointing it at tmp keeps this test off the real costs.json.
const cost = require(path.resolve(__dirname, "..", "cost.js"));

const MODEL = "nvidia/nemotron-3-ultra-550b-a55b";
const RATE = 0.0008; // per 1k tokens, in and out, for this model
const EXPECTED = (1000 * RATE + 500 * RATE) / 1000; // 0.0012

let seq = 0;
function priceWith(agentId, usage) {
  cost.recordCost(agentId, MODEL, "nvidia", usage);
  const rec = cost.getAgentCosts(agentId).records.slice(-1)[0];
  return rec.costUsd;
}

test("snake_case usage, the shape every caller passes, prices correctly", () => {
  const v = priceWith("snake-" + seq++, { prompt_tokens: 1000, completion_tokens: 500 });
  assert.ok(Number.isFinite(v), "costUsd must be finite, got " + v);
  assert.ok(Math.abs(v - EXPECTED) < 1e-12, "expected " + EXPECTED + ", got " + v);
});

test("camelCase usage still prices correctly", () => {
  const v = priceWith("camel-" + seq++, { promptTokens: 1000, completionTokens: 500 });
  assert.ok(Math.abs(v - EXPECTED) < 1e-12, "expected " + EXPECTED + ", got " + v);
});

test("no usage shape can produce NaN, so JSON cannot persist null", () => {
  for (const usage of [
    { prompt_tokens: 7, completion_tokens: 3 },
    { promptTokens: 7, completionTokens: 3 },
    { prompt_tokens: 0, completion_tokens: 0 },
    {},
  ]) {
    const id = "shape-" + seq++;
    cost.recordCost(id, MODEL, "nvidia", usage);
    const a = cost.getAgentCosts(id);
    assert.ok(Number.isFinite(a.records.slice(-1)[0].costUsd),
      "NaN leaked from usage " + JSON.stringify(usage));
    assert.notStrictEqual(JSON.stringify(a.records.slice(-1)[0].costUsd), "null",
      "NaN would serialise to null on disk");
    assert.ok(Number.isFinite(a.monthly), "monthly must be finite");
  }
});

test("daily and monthly accumulators stay finite across many calls", () => {
  const id = "accum-" + seq++;
  for (let i = 0; i < 5; i++) {
    cost.recordCost(id, MODEL, "nvidia", { prompt_tokens: 1000, completion_tokens: 500 });
  }
  const a = cost.getAgentCosts(id);
  assert.ok(Number.isFinite(a.daily), "daily must be finite, got " + a.daily);
  assert.ok(Number.isFinite(a.monthly), "monthly must be finite, got " + a.monthly);
  assert.ok(Math.abs(a.monthly - EXPECTED * 5) < 1e-9, "expected 5x accrual");
});

test("provider key is case-insensitive, matching the lowercase PRICING table", () => {
  // response.provider is uppercase ("NVIDIA") but PRICING is keyed "nvidia".
  // A case-sensitive lookup silently fell through to the generic 0.0004/1k
  // rate and halved the price of every real call.
  const lower = priceWith("case-lower-" + seq++, { prompt_tokens: 1000, completion_tokens: 1000 });
  const upper = priceWith("case-upper-" + seq++, { prompt_tokens: 1000, completion_tokens: 1000 });
  assert.strictEqual(lower, upper, "NVIDIA and nvidia must price identically");
  assert.ok(Math.abs(lower - (2000 * 0.0008) / 1000) < 1e-12,
    "expected the real NVIDIA rate, got " + lower);
});

test("unknown provider and unknown model still yield a finite number", () => {
  for (const [provider, model] of [["nope", "some/model"], ["nvidia", "not-a-real-model"]]) {
    const id = "unknown-" + seq++;
    cost.recordCost(id, model, provider, { prompt_tokens: 10, completion_tokens: 10 });
    const v = cost.getAgentCosts(id).records.slice(-1)[0].costUsd;
    assert.ok(Number.isFinite(v), provider + "/" + model + " must not yield NaN");
  }
});

test("the persisted file contains no null costs", () => {
  const raw = JSON.parse(fs.readFileSync(path.join(tmp, "costs.json"), "utf8"));
  for (const [agent, a] of Object.entries(raw)) {
    assert.ok(a.daily === null || Number.isFinite(a.daily),
      agent + ".daily is null on disk");
    assert.ok(a.monthly === null || Number.isFinite(a.monthly),
      agent + ".monthly is null on disk");
    for (const r of a.records || []) {
      assert.ok(Number.isFinite(r.costUsd), agent + " has a null/NaN costUsd on disk");
    }
  }
});

test.after(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});
