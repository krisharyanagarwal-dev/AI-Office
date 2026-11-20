# dost/ module map

Navigable map of the package. Subpackages group related modules; everything else sits at `dost/` root as an entry point or widely-shared module.

## Entry points (root)
- `dost.py` — main CLI + core (`dost_respond`, `generate_daily_briefing`, workspace cmds). 2.4k lines.
- `../dost.py` — thin wrapper that loads `dost/dost.py` and `dost/trading/strategy_pipeline.py` by path.
- `cli_autocomplete.py` — shell completion.
- `setup_wizard.py` — first-run config.
- `chat_core.py` — HTTP chat server.
- `context_builder.py` — assembles context for prompts.
- `data_access.py` — OHLCV + synthetic data (widely imported).
- `models.py` — shared dataclasses / schemas.
- `morning_digest.py` — daily brief generator.
- `api_marketplace.py` — API exposure.
- `pet_server.py` — pet-page demo surface (serves `pet_page.html`).
- `deploy-mini.py` — deploy to the mac mini.
- `openai_components.py` — OpenAI SDK glue.

## Trading
- `trading/strategy_engine.py` — signal generation.
- `trading/strategy_pipeline.py` — dispatch → backtest → cost-size → validate.
- `trading/backtest_engine.py` — backtest runner.
- `trading/oos_validator.py` — out-of-sample validation.
- `trading/position_sizer.py` — Kelly / cost-aware sizing.
- `trading/market_data.py` — market data access.

## Bots / integrations
- `bots/slack_bot.py`, `bots/teams_bot.py`, `bots/telegram_bot.py`.
- `bots/zapier.py` — Zapier webhooks.
- `bots/webhooks.py` — generic incoming webhooks.

## Ops / reliability
- `ops/circuit_breaker.py`, `ops/retry.py` — fault tolerance.
- `ops/sla.py` — SLA tracking.
- `ops/proactive_monitor.py` — watchdog.
- `ops/structured_logging.py`, `ops/audit_log.py`, `ops/changelog.py` — logging.
- `ops/metrics_export.py` — Prometheus / stats.
- `ops/backup_state.py` — state snapshots.
- `ops/config_validator.py` — config checks.

## Security / governance
- `security/rbac.py`, `security/sso.py`, `security/api_keys.py`.
- `security/data_export.py`, `security/data_deletion.py` — GDPR flows.

## Voice
- `voice/voice_chat.py`, `voice/voice_cli.py`.
- `siri_dost.sh` — Siri Shortcut entrypoint (companion asset in `docs/Siri-Dost.shortcut`).

## Memory
- `memory_pkg/persistent_memory.py` — long-term store.
- `memory_pkg/memory_learner.py` — extracts facts from conversations.
- `memory_pkg/jarvis.py`, `memory_pkg/jarvis_selftest.py` — Jarvis-mode memory.
- `jarvis_memory/` — runtime data dir (not a package).

## Collaboration / workspace
- `collab/workspace.py` — multi-tenant workspaces.
- `collab/shared_tasks.py` — task sharing.
- `collab/task_assignment.py` — routing to workers.
- `collab/collaborative_findings.py` — shared research notes.
- `collab/activity_feed.py` — timeline.

## Automation / briefings
- `morning_digest.py` — daily brief generator (root).
- `briefings/` — generated briefings (runtime).
- `exports/` — generated exports (runtime).

## Marketplace / billing
- `api_marketplace.py` — API exposure (root).
- `billing/meter.py`, `billing/plans.py` — metering + plans.

## SDK
- `sdk/python/` — Python client library.

## Deployment
- `deploy-mini.py` — deploy to the mac mini (root).
- `mini/dost_mini_server.py`, `mini/pet_page.html` — mini-side server.

## Runtime data (gitignored)
- `conversation.json` — current session state.
- `history.jsonl` — append-only log.
- `pet_page.html` — static asset served by `pet_server.py`.
- `jarvis_memory/`, `briefings/`, `exports/` — generated.

## Tests
- `tests/test_golden_dataset.py` — regression on canned prompts.
- `tests/test_hallucination.py` — factual-grounding checks.
- `tests/test_prompt_mutation.py` — robustness.
- `tests/test_chaos.py` — fault injection.
- `tests/test_load.py` — concurrency.
- `tests/test_answer_consistency.py` — determinism.

## Docs
- `../README.md` — package overview.
- `docs/API_DOCUMENTATION.md` — public API.
- `docs/SIRI_SETUP.md` — Siri wiring.
- `docs/COMPANY_SYSTEM_PROMPT.md` — org-level system prompt.
- `docs/tier-c-review-sheet.md` — review checklist.
- `docs/Siri-Dost.shortcut` — the shortcut binary.
