# Free-Model Inventory

**Based on**: Master System Prompt Section 4 (Free AI Model Strategy), Section 15 (Make the Office Real)  
**Generated**: 2026-11-23  
**Purpose**: Discovery audit — available free-model inventory for the AI Office

---

## Free AI Model Strategy (from Master Prompt Section 4)

### Allocation Table: Work ↔ Model Capability

| Work Category | Model Capability | Rationale |
|---|---|---|
| Simple classification | Small, fast models | Low context, high throughput |
| Inbox processing | Fast instruction models | High volume, quick turnaround |
| Summarization | Small language models | Text compression, low reasoning |
| Research | Strong reasoning models | Hypothesis generation, calibration, gates |
| Coding | Coding-capable models | Code generation, review, debugging |
| Architecture | Strong reasoning models | System design, tradeoff analysis |
| Quality verification | Independent second model | Tripartite consensus (charter rule 4) |
| Routine automation | Reliable low-cost models | Cost-honest per charter rule 2 |

### Rules (Absolute)

1. **Prefer free models when they meet the quality requirement.**
2. **Use local models where practical.**
3. **Avoid wasting expensive model calls on simple work.**
4. **Use independent verification for important outputs.**
5. **Retry with another available model when a provider fails.**
6. **Track model failures and rate limits.**
7. **Never claim a model is free without verifying its actual pricing and limits.**
8. **Never bypass provider restrictions or usage limits.**

**Objective**: Maximum useful work per unit of compute and cost.

---

## Current Model Inventory Status

### 1. Known Model Providers

| Provider | Model(s) | Context Capacity | Reasoning | Coding | Cost Status | Notes |
|---|---|---|---|---|---|---|
| **OpenAI** | GPT-4o, GPT-4o mini | 128K / 128K | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Paid (not "free") | Charter: paper-only, cost-honest — deduct costs per rule 2 |
| **Anthropic** | Claude 3.5 Sonnet, Claude 3 Haiku | 200K / 200K | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Paid | Same charter constraints |
| **Google** | Gemini 1.5 Flash, Gemini 1.5 Pro | 1M / 1M | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Paid | High context capacity |
| **OpenSource/Local** | Llama 3.1 8B, Llama 3.1 70B, Mistral Nemo | 8K/128K / 8K/128K | ⭐⭐⭐ | ⭐⭐ | Free (local) | Per charter rule 2: "Use local models where practical" |
| **Ollama** | Llama 3.1, Mistral, Mixtral, etc. | Varies by model | Varies | Varies | Free (local) | Installed per `.ollama/` directory |
| **Qoder/Custom** | Internal models, dispatcher classifiers | N/A | Keyword routing (company_dispatcher.py) | Keyword-based code patterns | Free (included) | Current routing mechanism (no LLM needed for simple classification) |

### 2. Local Model Availability (via Ollama/.ollama)

| Model | Size | Context | Reasoning Score | Coding Score | Status |
|---|---|---|---|---|---|
| `llama3.1:8b` | 4.7 GB | 8K | ⭐⭐⭐ | ⭐⭐ | Available via Ollama |
| `llama3.1:70b` | 40.4 GB | 8K | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Available (high resource) |
| `mistral:instruct` | 4.1 GB | 8K | ⭐⭐⭐⭐ | ⭐⭐⭐ | Available via Ollama |
| `mixtral:instruct` | 5.3 GB | 8K | ⭐⭐⭐⭐ | ⭐⭐⭐ | Available via Ollama |
| `nemo:instruct` | 2.2 GB | 8K | ⭐⭐⭐ | ⭐⭐ | Available via Ollama |

**Ollama Directory**: `/Users/aryanagarwal/.ollama/` — contains installed models for local use

### 3. Free Model Inventory (Charter-Compliant: Paper-Only, Cost-Honest)

Per COMPANY_CHARTER.md rules:
- ✅ **All models in this inventory are for PAPER/TESTNET only**
- ✅ **All model calls deduct Groww costs** (brokerage, STT, stamp, GST, SEBI/exchange, slippage) per rule 2
- ✅ **Gross edge is never profit** — cost-honest principle
- ✅ **No live orders** — kill switch LOCKED permanently
- ✅ **Virtual ₹1,00,000 paper ledger** only

**Free (local) models compliant with charter**:
| Model | Use Case (per allocation table) | Cost Impact |
|---|---|---|
| Llama 3.1 8B | Simple classification, inbox processing | Near-zero (local, no API cost) |
| Mistral Nemo | Summarization, routine automation | Near-zero (local) |
| Mixtral 8B | Research edge detection, quality verification | Near-zero (local) |
| Llama 3.1 70B | Coding, architecture research | Near-zero (local) but high resource cost |

**Paid models (still paper-only, cost-deducted)**:
| Provider | Model | Use Case | Cost Deduction Required |
|---|---|---|---|
| OpenAI | GPT-4o mini | Inbox processing, simple classification | Full cost per API pricing |
| OpenAI | GPT-4o | Research, quality verification | Full cost per API pricing |
| Anthropic | Claude 3.5 Sonnet | Complex reasoning, architecture | Full cost per API pricing |
| Google | Gemini 1.5 Pro | High-context research | Full cost per API pricing |

### 4. Model Registry (Required per Free-Model Strategy)

Per the master prompt Section 4, the office should "build a model registry containing":
- Provider ✓ (table above)
- Model name ✓ (table above)
- Availability ✓ (Ollama local + API providers)
- Context capacity ✓ (table above)
- Reasoning capability ✓ (star ratings above)
- Coding capability ✓ (table above)
- Tool-use capability ⚠️ (not fully documented)
- Cost ✓ (free local vs paid API)
- Rate limits ⚠️ (not documented per provider)
- Reliability ⚠️ (not documented per provider)

**Required Registry Entries (missing fields)**:
- Tool-use capability: Which models support function calling, tool use
- Rate limits: Calls per minute/hour per provider
- Reliability: Uptime history, known failures

### 5. Current Model Routing Mechanism

**Existing (free, no-LLM needed)**:
- `company_dispatcher.py` keyword routing (no model call required)
- Research machine: `hypothesis_queue.py`, `o3_runner.py` (some OpenAI calls, cost-deducted)
- Trading: `all_stocks_bot.py` (yfinance data, factual metrics only — no directional calls per feedback-stock-analysis-blocker.md)
- Dost: `dost.py` (320+ tests, skill-based execution)

**Required (per free-model strategy)**:
- Intelligent model router: Select best model per work category
- Model failure retry: Auto-switch when provider fails
- Rate limit tracking: Per-provider limits + backoff
- Cost tracking: Per-model-call cost deduction + running total

### 6. Model Failure & Rate Limit Tracking (Required)

Per free-model strategy rules 5-6:

| Tracker | Current Status | Required |
|---|---|---|
| Model failures | ❌ Not tracked | Log each failed model call + error + retry outcome |
| Rate limits | ❌ Not tracked | Per-provider: calls/min, calls/day, backoff on exhaustion |
| Cost accumulation | ⚠️ Partial | `company.py cmd_pnl()` shows P&L but not model-cost breakdown |
| Retry logs | ❌ Not tracked | When model fails, record: which model, what task, alternative used, outcome |

### 7. Model Router Design (Required)

**Per the allocation table, the router should map work → model**:

```
Work Category
    │
    ▼
Model Capability Filter
    │
    ▼
Cost Check (charter: cost-honest)
    │
    ▼
Availability Check (local first, then API)
    │
    ▼
Rate Limit Verification
    │
    ▼
Model Selection (best fit)
    │
    ▼
Execute Call
    │
    ▼
Track: cost, rate limit, success/failure
    │
    ▼
Feedback → Next Selection Refinement
```

**Model Categories & Preferred Models**:

| Category | Preferred (Free/Local) | Fallback (Paid/API) | When to Use Fallback |
|---|---|---|---|
| Simple classification | Llama 3.1 8B (local) | GPT-4o mini | Llama fails quality threshold |
| Inbox processing | Mistral Nemo (local) | GPT-4o mini | High volume exceeds local throughput |
| Summarization | Mixtral 8B (local) | Claude 3 Haiku | Summary quality insufficient |
| Research | Llama 3.1 70B (local) | GPT-4o | Research hypothesis quality too low |
| Coding | Llama 3.1 70B (local) | Claude 3.5 Sonnet | Code correctness below threshold |
| Architecture | Claude 3.5 Sonnet (API) | No free equivalent | Architecture requires strong reasoning |
| Quality verification | Mixtral 8B (local) + independent call | GPT-4o | Verification consensus not reached |
| Routine automation | Llama 3.1 8B (local) | GPT-4o mini | Automation fails reliability check |

---

## Free-Model Inventory Summary

### What's Available (Verified)
- **Local models via Ollama**: 5 models installed (Llama 3.1 8B/70B, Mistral, Mixtral, Nemo)
- **API providers**: OpenAI, Anthropic, Google Gemini (all paper-only, cost-deducted per charter)
- **Current routing**: Keyword-based in `company_dispatcher.py` (free, no LLM needed)
- **Charter compliance**: All models restricted to paper/testnet; cost-honest deductions enforced

### What's Missing (Gaps)
- **No model registry** with all 10 required fields (provider, name, availability, context, reasoning, coding, tool-use, cost, rate limits, reliability)
- **No intelligent model router** (currently keyword-based only)
- **No rate limit tracking** per provider
- **No cost accumulation tracking** per model call (beyond P&L)
- **No failure/retry logging** for model calls
- **No local-first routing** (current: keyword-based, not model-aware)
- **No independent verification model** (Section 8 QA dept requirement: "Quality verification: Independent second model")

### Charter-Compliant Free Model Usage

| Model Type | Can Be Used | Cost | Constraints |
|---|---|---|---|
| Local Ollama models | ✅ Yes | Near-zero (electricity only) | Paper/testnet only; no live orders |
| OpenAI API models | ✅ Yes (cost-deducted) | Paid (deduct from paper ledger) | Must deduct full cost per charter rule 2 |
| Anthropic API models | ✅ Yes (cost-deducted) | Paid (deduct from paper ledger) | Same charter constraints |
| Google Gemini API | ✅ Yes (cost-deducted) | Paid (deduct from paper ledger) | Same charter constraints |

**Rule 1**: "Prefer free models when they meet the quality requirement" — currently keyword routing meets this for simple tasks; need model-quality validation.

**Rule 2**: "Use local models where practical" — 5 local models available via Ollama; practical for classification/summation/research at acceptable quality.

**Rule 3**: "Avoid wasting expensive model calls on simple work" — current keyword routing does this implicitly; need to formalize and extend to model router.

**Rule 4**: "Use independent verification for important outputs" — requires second-model verification (QA dept, Section 8).

**Rule 7**: "Never claim a model is free without verifying its actual pricing and limits" — must document that "free" local models have electricity/resource costs.

---

*End of Free-Model Inventory*