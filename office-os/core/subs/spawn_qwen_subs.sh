#!/bin/bash
# spawn_qwen_subs.sh - Spawn Qwen3.5-9B worker subs for opencode sessions
#
# Usage:
#   ./spawn_qwen_subs.sh spawn <session_id> [worker_count]
#   ./spawn_qwen_subs.sh assign <session_id> <worker_id>
#   ./spawn_qwen_subs.sh release <session_id> [worker_id]
#   ./spawn_qwen_subs.sh list
#   ./spawn_qwen_subs.sh status
#   ./spawn_qwen_subs.sh submit <session_id> "<prompt>" [--worker worker-id]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
LAUNCHER="$SCRIPT_DIR/session_worker_launcher.py"
SUBMITTER="$SCRIPT_DIR/session_task_submit.py"

case "${1:-}" in
  spawn)
    SESSION="${2:-session-$(date +%s)}"
    COUNT="${3:-1}"
    echo "Spawning Qwen3.5-9B subs for session: $SESSION ($COUNT workers)"
    $PYTHON "$LAUNCHER" spawn "$SESSION" "$COUNT"
    ;;
  assign)
    echo "Assigning worker $3 to session $2"
    $PYTHON "$LAUNCHER" assign "$2" "$3"
    ;;
  release)
    if [ -n "$3" ]; then
      echo "Releasing worker $3 from session $2"
      $PYTHON "$LAUNCHER" release "$2" "$3"
    else
      echo "Releasing all workers from session $2"
      $PYTHON -c "
import json, sys
reg = json.load(open('$SCRIPT_DIR/session_registry.json'))
s = reg['sessions'].get('$2', {})
for w in s.get('workers', []):
    print(w)
"
    fi
    ;;
  list)
    $PYTHON "$LAUNCHER" list
    ;;
  status)
    $PYTHON "$LAUNCHER" status
    ;;
  submit)
    shift
    $PYTHON "$SUBMITTER" "$@"
    ;;
  *)
    echo "Usage: $0 {spawn|assign|release|list|status|submit} [args...]"
    echo ""
    echo "  spawn <session_id> [count]  - Spawn Qwen3.5-9B workers for a session"
    echo "  assign <session> <worker>   - Assign a free worker to a session"
    echo "  release <session> [worker]  - Release worker(s) from a session"
    echo "  list                        - List all sessions and workers"
    echo "  status                      - Show detailed worker status"
    echo "  submit <session> <prompt>   - Submit a task to a session's worker"
    echo ""
    echo "Workers: worker-1 (127.0.0.1:11434)"
    echo "Model: hauhaucs/qwen3.5-9b-uncensored-aggressive"
    exit 1
    ;;
esac