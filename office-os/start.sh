#!/bin/bash
# Start Office OS orchestrator in background
cd /Users/aryanagarwal/office-os

# Kill any existing orchestrator
pkill -f "core/orchestrator.py" 2>/dev/null || true

# Start orchestrator in background with nohup
nohup python3 core/orchestrator.py > logs/orchestrator.log 2>&1 &
echo $! > logs/orchestrator.pid

echo "Office OS orchestrator started (PID: $(cat logs/orchestrator.pid))"
echo "Logs: logs/orchestrator.log"
echo ""
echo "To attach to a worker agent's tmux session:"
echo "  tmux -L office-os -S /tmp/office-os-tmux attach -t <agent_id>"
echo ""
echo "To check status:"
echo "  python3 -c \"from core.orchestrator import Orchestrator; o=Orchestrator(); print(o.status())\""