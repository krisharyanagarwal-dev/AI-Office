# Siri + Dost setup (Wave 4-S2)

Siri integration for Dost — no Telegram token needed. You speak to Siri, Dost
replies, and your iPhone speaks it back.

## Files

- `dost/siri_dost.sh` — shell script Shortcuts calls. Takes an optional message.
  - No message → `dost --briefing` (daily briefing)
  - With message → `dost_respond` directly (a warm spoken reply, not JSON)
- `dost/Siri-Dost.shortcut` — plist blueprint of the Shortcut workflow
- `dost/SIRI_SETUP.md` — this file

## Boundaries (unchanged)

Paper-only. Kill switch locked. Tier C human-only. No live orders. Free tiers
only. No new strategy hunting. Nothing here places trades or changes systems.

---

## Step 1 — Make the script executable and test it

Open Terminal on your Mac and run:

```bash
chmod +x /Users/aryanagarwal/AI-Office/dost/siri_dost.sh
```

Test the briefing (no message):

```bash
/Users/aryanagarwal/AI-Office/dost/siri_dost.sh
```

Test with a message:

```bash
/Users/aryanagarwal/AI-Office/dost/siri_dost.sh "research NSE options edges"
```

Both should print clean speakable text. If anything is missing (python3, the
script, Dost itself), the script prints a friendly fallback instead of failing.

## Step 2 — Add the Shortcut on your iPhone

1. Open the **Shortcuts** app on iPhone (iOS 16+).
2. Tap **+** → **New Shortcut** → name it **Siri Dost**.
3. Add these actions, in order:
   1. **Ask for Input** — Prompt: "Ask Dost…" (this is what Siri asks you).
   2. **Run Shell Script** — Shell script path:
      `/Users/aryanagarwal/AI-Office/dost/siri_dost.sh`
      Enable **Pass Input** so your spoken message is passed as `$1`.
   3. **Speak Text** — speaks the script's output. Adjust rate/pitch to taste.

   If you want the briefing instead of a free-form message, replace step 1 with
   **No Input** and pass no argument to the script (it runs `--briefing`
   automatically when `$1` is empty).

4. Tap the **…** (details) on the shortcut → **Add to Siri** → record a phrase,
   e.g. **"Hey Siri, ask Dost"** or **"Ask Dost"**.

The plist at `dost/Siri-Dost.shortcut` documents the exact same three actions
(ask input → run shell script → speak text) and can be used as a reference if
you rebuild the shortcut later.

## Step 3 — Trigger via Siri

Say: **"Hey Siri, ask Dost"** → Siri prompts "Ask Dost…" → say your message,
e.g. "research NSE options edges" or "give me the briefing" → Dost replies and
iPhone speaks it.

If you say nothing at the prompt, the script runs with no message and reads the
daily briefing.

## Step 4 — Configure the shell script path

The script auto-resolves its own location (`SCRIPT_DIR` → parent = company
root → `dost.py`), so you normally don't need to edit anything. If you move the
files, keep `siri_dost.sh` inside `dost/` next to `dost.py`, or update
`WFShellScriptPath` in the Shortcut action to the new absolute path.

Required on the Mac: `python3` and `perl` (both ship with macOS). The Shortcut
runs the shell script on the device it's installed on.

## Troubleshooting

- Shortcut says "The operation couldn't be completed" → check the shell script
  path is exact and the script is `chmod +x`.
- Siri speaks the fallback ("Sorry, I'm having trouble reaching Dost…") →
  run `siri_dost.sh` in Terminal to see the real error (printed to stderr).
- Nothing spoken → in the Shortcut, confirm **Speak Text** is the last action
  and its input is the output of **Run Shell Script**.
- Dost replies but isn't grounded in live data → check `dost --briefing` and
  `dost --status` in Terminal first.
