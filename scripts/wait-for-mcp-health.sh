#!/bin/bash
# Wait for all MCP services to be healthy

echo "Waiting for MCP services to become healthy..."

# Wait for each service
SERVICES="filesystem git github postgres docker playwright"
TIMEOUT=60
START_TIME=$(date +%s)

for service in $SERVICES; do
  echo "Waiting for $service..."
  while [ $(($(date +%s) - START_TIME)) -lt $TIMEOUT ]; do
    if docker compose -f docker-compose.mcp.yml ps $service | grep -q "healthy"; then
      echo "✓ $service is healthy"
      break
    fi
    sleep 2
  done

  if [ $(($(date +%s) - START_TIME)) -ge $TIMEOUT ]; then
    echo "✗ Timeout waiting for $service to become healthy"
    exit 1
  fi
done

echo "All MCP services are healthy!"
