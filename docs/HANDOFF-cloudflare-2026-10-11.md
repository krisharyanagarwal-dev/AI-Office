# Handoff — Cloudflare Workers AI provider

Date: 2026-10-11 · Repo: `/Users/aryanagarwal/src/openalice-fleet` · Branch: `feat/acceptance-coverage`

## Status: committed as `d803ddb`, NOT pushed

```
services/cloudflare_models.json | 425 +++++  (new)
services/free_harness.py        | 114 +++++
services/openalice_config.py    |   1 +
```

Quality gate: unchanged vs HEAD baseline. Same 4 stages red before and after
(offline tests, secret scan, watchdog mypy, pyright) — all pre-existing, none in
touched files. Verified via throwaway worktree at HEAD.

## What's wired

Harness `cloudflare` provider — 23 models, all confirmed live on Workers **Free** plan:

- base_url `https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/v1`
- creds from env: `CLOUDFLARE_API_TOKEN` + `CF_ACCOUNT_ID` (never in code)
- `cloudflare/` and `@cf/` prefix routing
- `check_cloudflare_quota()` fails closed when either var is missing

opencode: `~/.config/opencode/opencode.json` → `cloudflare` provider, same 23.
Restart opencode to pick it up. Use as `cloudflare/qwen3.8-27b`.

## Verified-live models (23)

Qwen 4: `qwen3.8-27b`, `qwen2.5-coder-32b-instruct`, `qwq-32b`, `qwen3-30b-a3b-fp8`
OpenAI 2: `gpt-oss-120b`, `gpt-oss-20b`
Meta 5: `llama-3.3-70b-instruct-fp8-fast`, `llama-4-scout-17b-16e-instruct`,
        `llama-3.1-8b-instruct-fp8`, `llama-3.2-3b-instruct`, `llama-3.2-1b-instruct`
Mistral 2: `mistral-small-3.1-24b-instruct`, `mistral-7b-instruct-v0.2-lora`
Google 3: `gemma-4-26b-a4b-it`, `gemma-7b-it-lora`, `gemma-2b-it-lora`
Other 5: `nvidia/nemotron-3-120b-a12b`, `deepseek-ai/deepseek-r1-distill-qwen-32b`,
         `zai-org/glm-4.7-flash`, `meta-llama/llama-guard-3-8b`,
         `aisingapore/gemma-sea-lion-v4-27b-it`, `ibm-granite/granite-4.0-h-micro`

Neuron cost per short completion: granite-micro 0.07 (cheapest) · gemma-4 0.63 ·
llama-3.3-70b 1.48 · qwen2.5-coder 2.22 · gpt-oss-120b 5.70 · qwen3.8-27b 10.19

## Excluded 18 — all fail, don't re-add

| Reason | Models |
|---|---|
| Workers Free plan gate (5035) | `kimi-k2.6`, `kimi-k2.7-code`, `glm-5.2`, `glm-5.3`, `glm-5.3-flash`, `deepseek-v4-pro-0813`, `deepseek-v4-flash-0731` |
| Signed Model Agreement | `llama-3.2-11b-vision-instruct` |
| Account allowlist | `swiss-ai/apertus-v1.5-8b` |
| Not in catalog | `eurollm-9b-it`, `mistral-large-2407` |
| Wrong API shape | `clef`, `clef-flash`, `clef-omni` |
| Gateway-paid, zero balance | `anthropic/claude-*` |

## Gotchas that cost time

1. **Namespaces are not guessable.** Docs list bare slugs; wire needs
   `@cf/<vendor>/<slug>`. 12 were wrong on first pass. Confirm via:
   `GET /client/v4/accounts/$CF_ACCOUNT_ID/ai/models/search`
   Notable: `@cf/zai-org/` not `@cf/zai/`, `@cf/ibm-granite/` not `@cf/ibm/`,
   `@cf/mistral/` vs `@cf/mistralai/` (inconsistent upstream), `@cf/cloudflare/clef*`.

2. **Reasoning models return `content: null`** with text in `reasoning`.
   A naive `.strip()` on content raises. Seen on gpt-oss, qwen3, nemotron,
   glm-4.7-flash. **The harness may not handle this — verify before relying on it.**

3. Chat endpoint returns **bare OpenAI shape** (no `success`/`result` wrapper).
   The `/ai/run/` endpoint DOES wrap. Parsers that check `d["success"]` fail on chat.

## Not done / next

- [ ] **Push `d803ddb`.** Then macmini (`/Users/a/trading/openalice-fleet`) gets it
      via origin/main. That's the intended path — do NOT hand-port to the other
      local trees, they have already diverged.
- [ ] **Revoke 3 old `cfut_` tokens** posted in plaintext in chat: `o8U22…`,
      `5vaPV…`, `Bm92R…`. Still live at time of writing. Also earlier: JWT, `mstrl_`,
      AWS key `19872f36…` / secret `2b1f4c17…`, `cfat_…` (that one is revoked).
- [ ] **Rotate the current token** — written plaintext to `~/.env` (mode 0600).
- [ ] `oa-strat/` and `openalice-fleet/` have NO cloudflare provider by design.
      `openalice-fleet` lacks mistral too — both are stale clones.
- [ ] `check_openrouter_quota` reports "$5 credits remaining" but
      `GET /api/v1/credits` returns `total_credits: 0`. Stale/buggy.
- [ ] Non-chat CF categories (embeddings, image, TTS, ASR, translation —
      43 models) are catalogued but nothing calls them. They need `/ai/run/`
      helpers with per-category request shapes.

## Other fleet state (pre-existing, unrelated)

Quality gate red on: 3 `test_trader_plist_consistency` failures, 1
`test_execution_safety` failure, 3 test-file secret-scan hits, 16 mypy +
17 pyright errors — all in `services/oa_watchdog.py`, untouched here.
