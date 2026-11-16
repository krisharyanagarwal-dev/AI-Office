#!/bin/bash
# Bounded reload: at most 4 agents per batch, one signal then wait, 150s bound.
# Usage: bounded_reload.sh <fix-ref> <agent1,agent2,...>
set -u
HIVE=/Users/a/trading/openalice-fleet/hive
cd "$HIVE"
FIX="$1"; LIST="$2"

IFS=',' read -ra ALL <<< "$LIST"
BATCH=4
i=0
n=0
FAILED=""
while [ $i -lt ${#ALL[@]} ]; do
  CHUNK=("${ALL[@]:$i:$BATCH}")
  n=$((n+1))
  JOINED=$(IFS=,; echo "${CHUNK[*]}")
  echo "  batch $n: $JOINED"
  /Users/a/.venvs/openalice/bin/python scripts/rolling_restart_agents.py \
      --apply --include-protected --fix "$FIX" --only "$JOINED" --timeout 150 >/tmp/_br.log 2>&1
  RC=$?
  if [ $RC -ne 0 ]; then
    FAILED="$FAILED ${CHUNK[0]}"
    echo "     restart tool rc=$RC; $(grep -c ABORT /tmp/_br.log) abort(s)"
    grep "ABORT" /tmp/_br.log | head -2 | sed 's/^/     /'
  else
    echo "     ok"
  fi
  # One signal, then wait. Never signal the same agent twice in a row.
  sleep 20
  i=$((i+BATCH))
done
echo "  batches run: $n   failed:${FAILED:- none}"
