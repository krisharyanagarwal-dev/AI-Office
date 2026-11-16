#!/bin/bash
# Production deployment script
set -e

echo "Deploying to production environment (localhost only)"
echo "Environment: PROD"

# Build packages
echo "Building packages..."
if [ -f package.json ]; then
  npm run build
fi

# Deploy to localhost:8443
echo "Starting production server on localhost:8443"
if [ -f package.json ]; then
  npm run start -- --port 8443 &
  PROD_PID=$!
  echo "Production server started with PID $PROD_PID"
fi

echo "Production deployment complete"
