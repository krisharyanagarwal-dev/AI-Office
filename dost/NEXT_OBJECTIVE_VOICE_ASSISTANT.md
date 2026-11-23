# Next Objective: Voice-First Persistent Assistant

## Outcome
User says "Hey Siri, ask dost to research AAPL earnings" → dost:
1. Wakes via Siri shortcut
2. Captures voice → text
3. Dispatches to fleet (research department)
4. Remembers context across sessions
5. Responds via TTS when done

## Components (all exist, need wiring)

| Component | Path | Status |
|-----------|------|--------|
| Siri entry | `dost/siri_dost.sh` | ✅ scaffold |
| Voice I/O | `dost/voice/` | ✅ scaffold |
| Chat engine | `dost/chat_core.py` | ✅ works |
| Memory | `dost/memory_pkg/`, `dost/jarvis_memory/` | ✅ exists |
| Fleet dispatch | `dost/dost.py --dispatch` | ✅ works |
| Departments | 6 depts in CLI | ✅ working |

## Gaps to Close

1. **Voice pipeline**: `siri_dost.sh` → `voice/stt.py` → `chat_core` → `voice/tts.py` → Siri
2. **Session persistence**: Load/save `jarvis_memory` per conversation_id
3. **Async dispatch + callback**: Fire `--dispatch`, poll for result, TTS response
4. **Wake word / always-on**: Optional `voice/daemon.py` for "Hey dost" without Siri

## Success Criteria (Verifiable)

- [ ] `siri_dost.sh "research AAPL"` → returns fleet task_id + speaks result
- [ ] Restart dost → "what was I researching?" → recalls AAPL context
- [ ] `python3 -m dost.voice.test_pipeline` passes (STT → chat → TTS roundtrip)
- [ ] Memory survives process restart (JSONL in `jarvis_memory/`)

## Constraints (Non-Negotiable)

- Paper/testnet only — no live orders
- Kill switch LOCKED
- `live_orders_allowed=false`, `autonomy.executor_enabled=false`
- Advisory-only cost cap
- No keys read/printed/copied
- Forbidden paths untouched

## Implementation Order (TDD)

1. **Test first**: `test_voice_pipeline.py` — STT→chat→TTS roundtrip with mocked fleet
2. **Memory adapter**: `jarvis_memory.load(session_id)` / `.save(session_id, messages)`
3. **Voice CLI**: `python3 -m dost.voice.cli "prompt"` → prints + speaks response
4. **Siri bridge**: Update `siri_dost.sh` to call voice CLI, return JSON to Shortcuts
5. **Async callback**: Background poll for fleet result → TTS when ready

## Files to Create/Modify

- `dost/voice/stt.py` — Speech-to-text (Whisper/MLX)
- `dost/voice/tts.py` — Text-to-speech (Kokoro/MLX)
- `dost/voice/cli.py` — Voice REPL entry point
- `dost/voice/test_pipeline.py` — TDD tests
- `dost/jarvis_memory/session.py` — Session load/save
- `dost/siri_dost.sh` — Wire to voice CLI
- `dost/dost.py` — Add `--voice` flag for Siri bridge

## Effort Estimate

~8-12 focused turns within 20-turn budget