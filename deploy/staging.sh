#!/bin/bash
# Staging deployment script
set -e

echo "Deploying to staging environment (localhost only)"
echo "Environment: STAGING"

# Build packages
echo "Building packages..."
if [ -f package.json ]; then
  npm run build
fi

# Deploy to localhost:8081
echo "Starting staging server on localhost:8081"
if [ -f package.json ]; then
  npm run start -- --port 8081 &
  STAGING_PID=$!
  echo "Staging server started with PID $STAGING_PID"
fi

echo "Staging deployment complete"
