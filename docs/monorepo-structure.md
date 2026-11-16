# Monorepo Structure

## Overview

This monorepo consolidates all AI-Office projects into a single repository with a clear package structure, deployment channels, and CI/CD pipelines.

## Directory Layout

```
AI-Office/
├── packages/
│   ├── core/              # Core Univer runtime (@univerjs/core)
│   ├── ui/                # UI framework (@univerjs/ui)
│   ├── utils/             # Utility functions (@univerjs/utils)
│   ├── office-os/         # Core infrastructure
│   ├── openalice/         # Agent orchestration
│   ├── nvidia-office/     # NVIDIA services
│   ├── trading/           # Trading logic
│   └── all-files/         # Shared utilities
├── deploy/
│   ├── dev.sh             # Localhost dev deployment
│   ├── staging.sh         # Localhost staging deployment
│   └── prod.sh            # Localhost production deployment
├── .github/workflows/
│   ├── build.yml          # Reusable build workflow
│   ├── test.yml           # Reusable test workflow
│   └── deploy.yml         # Reusable deploy workflow
├── README.md
└── specs/
    └── monorepo.md
```

## Deployment Channels

| Channel | Port | Purpose | Approval |
|---------|------|---------|----------|
| dev | localhost:8080 | Lightweight testing | Automatic on push |
| staging | localhost:8081 | Pre-production validation | Manual review |
| prod | localhost:8443 | Production deployment | Required approval |

## CI/CD Pipeline

- **Build**: Linting, dependency installation, package validation per package
- **Test**: Package-specific tests (Vitest for Node, pytest for Python)
- **Deploy**: Environment-specific deployment with pre-deploy validation

## Packages

### packages/core (@univerjs/core)
Foundation of Univer - runtime, dependency injection, command and mutation services, data models, configuration, localization, Facade entry point.

### packages/ui (@univerjs/ui)
Shared application UI framework, workbench services, menus, dialogs, clipboard services, Facade UI APIs.

### packages/utils (@univerjs/utils)
Utility functions for data processing, format conversion, DOM manipulation, configuration.

## Constraints

- All deployments limited to localhost
- Production deployments require manual approval
- Each package maintains independent test suite and build process
- GitHub Actions environments enforce protection rules per channel
