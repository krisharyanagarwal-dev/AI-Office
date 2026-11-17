# Dost — Your AI Chief of Staff

THE CLAUDE COMPANY's dost layer: natural language in, natural language out.
Not a chatbot clone — an action-oriented dost that runs research, trading,
fleet, ops, upgrade, and assistant departments on your behalf.

## How to Use

```bash
cd /Users/aryanagarwal/AI-Office

# Talk to your dost (auto-routes to the right department)
python dost.py "research NSE options edges"
python dost.py "backtest the bull put strategy"
python dost.py "write a memo on our findings" --department assistant
python dost.py "check provider health" --department ops
python dost.py "upgrade the system" --department upgrade

# Run real research pipeline commands
python dost.py report          # Monthly public research report
python dost.py register        # Pre-register a new hypothesis
python dost.py gate            # Verdict gate (needs hypothesis loaded)
python dost.py holdout         # Out-of-sample confirmation
python dost.py calibrate       # Predicted vs realized edge
python dost.py all             # Full pipeline (register→gate→holdout→calibrate→report)

# Proactive briefing
python dost.py --briefing

# Your profile & context
python dost.py --memory
python dost.py --context

# Via unified launcher
python company.py dost "message" [--department X]
python company.py dost --briefing
python company.py dost --health
```

## OpenAI Components

The dost uses OpenAI's API components for its language/reasoning layer:

| Component | OpenAI API | Fallback (OpenAI-compatible) |
|---|---|---|
| Chat / reasoning | `chat/completions` (GPT) | Groq `openai/gpt-oss-20b`, NVIDIA, DeepInfra |
| Whisper STT | `audio/transcriptions` | None (no free equivalent) |
| TTS | `audio/speech` | None (no free equivalent) |

Set `OPENAI_API_KEY` in `~/.env` to use OpenAI directly. Without it, the dost falls back to OpenAI-compatible endpoints already configured in this stack (Groq, NVIDIA NIM, DeepInfra). The reasoning layer decides which department to route to and whether to run a research command directly.

Check availability: `python dost.py --health`

## What the Dost Does

| You Say | Dost Does | Department |
|---|---|---|
| "research NSE edges" | Routes + explains research workflow | Research |
| "report" | Runs o3_runner.py report, shows real results | Research |
| "register" | Pre-registers a hypothesis, returns ID | Research |
| "backtest bull put" | Routes to paper engine, explains how to run | Trading |
| "write a memo" | Routes to assistant, offers capabilities | Assistant |
| "check health" | Routes to ops, points to P&L/dashboard | Ops |
| "upgrade the system" | Routes to upgrade, lists candidates | Upgrade |
| "fleet status" | Routes to fleet, explains Tier C block | Fleet |

## Boundaries (Absolute)

- **Paper only** — kill switch LOCKED, no live orders ever
- **Cost-honest** — Groww costs deducted before any edge claim
- **Verified** — producer ≠ verifier, tripartite consensus for major verdicts
- **No curve-fitting** — parameters fixed pre-registration, gate deterministic
- **Tier C human-only** — risk, execution, broker never automated

## Memory

Your dost remembers: your name, capital, risk tolerance, research interests,
and recent interactions. Stored in `dost/memory.json` and `dost/history.jsonl`.

## Daily Briefing

`python dost.py --briefing` generates a proactive morning brief: research
status, fleet health, trading P&L, provider health, and boundary reminders.
Saved to `dost/briefings/YYYY-MM-DD.txt`.

---\n\n*Your dost from THE CLAUDE COMPANY. Honest, cost-aware, self-upgrading.*