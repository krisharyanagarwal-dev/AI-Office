#!/bin/bash
# Office OS - Tmux Office Layout
# User-based: each user sees only their own tasks.
# Usage: bash ui/tmux_office.sh [user]
#
# Multiple panes showing live agent fleet views. No installs, uses tmux.

USER="${1:-aryan}"
SESSION="office-os"
SOCKET="/tmp/office-os-tmux"

# Kill existing session if any
tmux -L "$SESSION" -S "$SOCKET" kill-session 2>/dev/null || true

# Create main session with dashboard
tmux -L "$SESSION" -S "$SOCKET" new-session -d -s "$SESSION" -n "DASHBOARD" \
    "cd /Users/aryanagarwal/office-os && python3 ui/office_dashboard.py $USER"

# Split: top = dashboard, bottom = live logs
tmux -L "$SESSION" -S "$SOCKET" split-window -v -t "$SESSION:DASHBOARD" \
    "cd /Users/aryanagarwal/office-os && tail -f -n 30 logs/orchestrator.log"

# Resize: dashboard gets 60%, logs get 40%
tmux -L "$SESSION" -S "$SOCKET" resize-pane -t "$SESSION:DASHBOARD.1" -y 20

# Create second window: task board (user-specific)
tmux -L "$SESSION" -S "$SOCKET" new-window -t "$SESSION" -n "TASKS" \
    "watch -n 5 'cd /Users/aryanagarwal/office-os && python3 cli.py list-tasks --user $USER'"

# Create third window: provider status
tmux -L "$SESSION" -S "$SOCKET" new-window -t "$SESSION" -n "PROVIDERS" \
    "watch -n 10 'cd /Users/aryanagarwal/office-os && python3 cli.py providers'"

# Create fourth window: agent memory
tmux -L "$SESSION" -S "$SOCKET" new-window -t "$SESSION" -n "AGENTS" \
    "watch -n 10 'ls memory/ && echo \"---\" && for f in memory/memory_*.jsonl; do echo \"== $f ==\"; tail -3 \"$f\" 2>/dev/null; done'"

# Select dashboard window
tmux -L "$SESSION" -S "$SOCKET" select-window -t "$SESSION:DASHBOARD"

echo "Office OS tmux layout started as user: $USER"
echo ""
echo "Windows:"
echo "  DASHBOARD  - Full office UI (dashboard.py)"
echo "  TASKS      - Live task board (refreshes every 5s)"
echo "  PROVIDERS  - Provider health (refreshes every 10s)"
echo "  AGENTS     - Agent memory/logs (refreshes every 10s)"
echo ""
echo "Attach: tmux -L office-os -S /tmp/office-os-tmux attach"
echo "Navigate windows: Ctrl+b n (next), Ctrl+b p (prev)"
echo "Switch panes:   Ctrl+b o"
echo ""
