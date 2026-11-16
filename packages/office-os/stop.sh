#!/bin/bash
# Stop Office OS orchestrator
cd /Users/aryanagarwal/office-os

if [ -f logs/orchestrator.pid ]; then
    PID=$(cat logs/orchestrator.pid)
    kill $PID 2>/dev/null || true
    rm -f logs/orchestrator.pid
    echo "Office OS orchestrator stopped (PID: $PID)"
else
    pkill -f "core/orchestrator.py" 2>/dev/null || true
    echo "Office OS orchestrator stopped"
fi