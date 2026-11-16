#!/bin/bash
# Development deployment script
set -e

echo "Deploying to development environment (localhost only)"
echo "Environment: DEV"

# Build packages
echo "Building packages..."
if [ -f package.json ]; then
  npm run build
fi

# Deploy to localhost:8080
echo "Starting dev server on localhost:8080"
if [ -f package.json ]; then
  npm run start &
  DEV_PID=$!
  echo "Dev server started with PID $DEV_PID"
fi

echo "Development deployment complete"
