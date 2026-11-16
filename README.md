# AI-Office Monorepo

A consolidated monorepo for AI-Office projects with clear package structure, deployment channels, and CI/CD pipelines.

## Directory Layout

```
AI-Office/
├── packages/
│   ├── core/              # @univerjs/core - Foundation of Univer
│   ├── ui/                # @univerjs/ui - Shared application UI framework
│   ├── utils/             # @univerjs/utils - Utility functions
│   ├── office-os/         # Core infrastructure
│   ├── openalice/         # Agent orchestration
│   ├── nvidia-office/     # NVIDIA services integration
│   ├── trading/           # Trading logic (alpha-system)
│   ├── all-files/         # Shared utilities
│   └── qoder-session-floor/ # Qoder session management
├── deploy/
│   ├── dev.sh             # Localhost dev deployment
│   ├── staging.sh         # Localhost staging deployment
│   └── prod.sh            # Localhost production deployment
├── .github/workflows/
│   ├── build.yml          # Reusable build workflow
│   ├── test.yml           # Reusable test workflow
│   └── deploy.yml         # Reusable deploy workflow
├── data/                  # Runtime data (gitignored)
├── docs/                  # Documentation
├── scripts/               # Standalone scripts and tools
└── specs/
    └── monorepo.md
```

## Packages

| Package | Type | Description |
|---------|------|-------------|
| `@univerjs/core` | TypeScript | Runtime, DI, commands, mutations, data models |
| `@univerjs/ui` | TypeScript | Workbench services, menus, dialogs, clipboard |
| `@univerjs/utils` | TypeScript | Data processing, format conversion, DOM manipulation |
| `office-os` | Python | Core infrastructure, agents, config, architecture |
| `openalice` | Python | Agent orchestration, command center |
| `nvidia-office` | TypeScript | NVIDIA NIM integration |
| `trading` | Python | Alpha trading system, backtesting |
| `all-files` | TypeScript/Python | Shared utilities |
| `qoder-session-floor` | Python | Qoder session management |

## Deployment Channels

| Channel | Port | Purpose | Approval |
|---------|------|---------|----------|
| dev | localhost:8080 | Lightweight testing | Automatic on push |
| staging | localhost:8081 | Pre-production validation | Manual review |
| prod | localhost:8443 | Production deployment | Required approval |

## Quick Start

```bash
# Install dependencies (requires pnpm for JS packages)
cd packages/core && pnpm install

# Python packages
cd packages/office-os && pip install -e .
cd packages/trading && pip install -e .
cd packages/openalice && pip install -e .
cd packages/qoder-session-floor && pip install -e .
```

## CI/CD Pipeline

- **Build**: Linting, dependency installation, package validation per package
- **Test**: Package-specific tests (Vitest for Node, pytest for Python)
- **Deploy**: Environment-specific deployment with pre-deploy validation

All deployments limited to localhost. Production deployments require manual approval.
