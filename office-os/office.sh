#!/bin/bash
# Office OS - Start everything
# No installs. Uses existing Office OS + tmux + Python.
# User-based: each user sees only their own tasks.
#
# Usage:
#   bash office.sh              # Start orchestrator + open tmux office (user: aryan)
#   bash office.sh --user demo  # Start as demo user
#   bash office.sh --no-ui      # Start orchestrator only (background)
#   bash office.sh --ui-only    # Open tmux office only
#   bash office.sh --web        # Start localhost web server on port 8083
#   bash office.sh --all        # Start everything (orchestrator + web + tmux)

set -e

OFFICE_DIR="/Users/aryanagarwal/office-os"
cd "$OFFICE_DIR"

USER="${1:-aryan}"
if [[ "$USER" == "--user" && -n "$2" ]]; then
    USER="$2"
    shift 2
elif [[ "$USER" == --* ]]; then
    USER="aryan"
fi

case "${1:-}" in
  --no-ui|--ui-only|--web|--all|"")
    ;;
esac

# Re-parse first arg as mode
MODE="${1:-}"

case "$MODE" in
  --no-ui)
    echo "Starting Office OS orchestrator (background) as user: $USER"
    bash start.sh
    echo ""
    echo "Orchestrator running. Open tmux office with: bash office.sh --ui-only --user $USER"
    ;;
  --ui-only)
    echo "Opening tmux office as user: $USER"
    bash ui/tmux_office.sh "$USER"
    ;;
  --web)
    echo "Starting Office OS web server on http://localhost:8083"
    echo "Users: aryan (owner), demo (user)"
    python3 core/web_server.py
    ;;
  --all)
    echo "Starting Office OS orchestrator..."
    bash start.sh
    sleep 2
    echo ""
    echo "Starting web server on http://localhost:8083 (background)..."
    nohup python3 core/web_server.py > logs/web_server.log 2>&1 &
    echo $! > logs/web_server.pid
    echo ""
    echo "Opening tmux office layout as user: $USER"
    echo "(Press Ctrl+b d to detach from tmux and return to shell)"
    sleep 1
    bash ui/tmux_office.sh "$USER"
    exec tmux -L office-os -S /tmp/office-os-tmux attach
    ;;
  *)
    echo "Office OS - User-based agent fleet"
    echo ""
    echo "  bash office.sh [user]          Start orchestrator + tmux office"
    echo "  bash office.sh --user demo     Start as demo user"
    echo "  bash office.sh --no-ui         Start orchestrator only (background)"
    echo "  bash office.sh --ui-only       Open tmux office only"
    echo "  bash office.sh --web           Start localhost web server (port 8083)"
    echo "  bash office.sh --all           Start everything (orchestrator + web + tmux)"
    echo ""
    echo "Users:"
    python3 -c "import json; [print(f'  {u[\"id\"]}: {u[\"name\"]} ({u[\"role\"]})') for u in json.load(open('config/users.json'))['users'].values()]"
    echo ""
    echo "Web UI: http://localhost:8083 (login required)"
    ;;
esac
