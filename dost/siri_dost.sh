#!/usr/bin/env bash
#
# dost/siri_dost.sh — Siri / Shortcuts entry point for Dost.
#
# Usage (from the Shortcuts app):
#   ./siri_dost.sh                  # no message → reads the daily briefing
#   ./siri_dost.sh "research NSE edges"  # message → dost_respond directly
#
# Prints clean, speakable text to stdout. Always exits 0 so Shortcuts can
# speak a friendly fallback even when Dost is unreachable.
#
# Paper-only. Kill switch locked. No live orders. No Telegram token needed.
set -u

# Resolve directories relative to this script so the Shortcut keeps working
# no matter where it is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
COMPANY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DOST_CLI="$COMPANY_DIR/dost.py"

SORRY="Sorry, I'm having trouble reaching Dost right now. Please try again later."

# Clean Dost output for speech:
#   1. Drop ANSI escape codes
#   2. Strip emoji symbols (📊 🤖 etc.) so "say" doesn't read their names.
#      Explicit Unicode ranges are used instead of \p{Emoji} because this
#      Perl's \p{Emoji} wrongly matches ASCII digits — numbers must stay
#      verbatim (Dost principle). Digits, ₹ and ≥ are preserved.
#   3. Trim whitespace and drop blank lines
clean_text() {
    sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' \
        | perl -CSD -pe 's/[\x{1F300}-\x{1F9FF}\x{2600}-\x{27BF}\x{FE0F}\x{200D}]//g' \
        | sed 's/[[:space:]]*$//' \
        | sed -e '/^[[:space:]]*$/d' -e 's/^[[:space:]]*//'
}

main() {
    # python3 must be available
    if ! command -v python3 >/dev/null 2>&1; then
        printf '%s\n' "$SORRY (python3 not found)"
        return 0
    fi

    # dost.py must exist
    if [ ! -f "$DOST_CLI" ]; then
        printf '%s\n' "$SORRY (dost.py not found)"
        return 0
    fi

    local output=""
    local msg="${1:-}"

    # Detect intent from the spoken message
    local lower_msg
    lower_msg="$(printf '%s' "$msg" | tr '[:upper:]' '[:lower:]')"

    if printf '%s' "$lower_msg" | grep -qiE "anything broken|system health|is everything ok|anything wrong|any alerts"; then
        # Siri alert phrase → run doctor and summarize anomalies
        output="$(python3 "$DOST_CLI" --doctor 2>/dev/null | grep -E "FAIL|FAILED|Anomaly|Quota" | head -5 || true)"
        if [ -z "$output" ]; then
            output="All systems look good. No anomalies detected."
        fi
    elif printf '%s' "$lower_msg" | grep -qiE "repeat that|say again|what did you say|last answer"; then
        # Voice repeat last answer → read from answer cache
        output="$(python3 -c "
import json
try:
    c = json.load(open('/Users/aryanagarwal/.openclaw/dost_answer_cache.json'))
    # Get the most recent cached answer
    if c:
        k = sorted(c.keys(), key=lambda x: c[x].get('cached_at', 0), reverse=True)[0]
        print(c[k].get('answer', 'No recent answer found.'))
    else:
        print('No recent answer to repeat.')
except Exception as e:
    print('Could not read answer cache.')
" 2>/dev/null)" || true
    elif [ -z "$msg" ]; then
        # No message → daily briefing (deterministic, no LLM needed)
        output="$(python3 "$DOST_CLI" --briefing 2>/dev/null)" || true
    else
        # Message → dost_respond directly (warm spoken reply).
        # Note: --dispatch would only queue a fleet task and print JSON,
        # which is not speakable, so we use dost_respond instead.
        output="$(python3 "$DOST_CLI" "$@" 2>/dev/null)" || true
    fi

    if [ -z "$output" ]; then
        printf '%s\n' "$SORRY"
        return 0
    fi

    printf '%s\n' "$output" | clean_text
}

main "$@"
