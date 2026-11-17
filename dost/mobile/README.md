# Dost Mobile

Mobile app skeleton for accessing THE CLAUDE COMPANY office fleet from mobile devices.

## Structure

```
mobile/
├── README.md
├── package.json
├── App.js              # Main app component
├── api.js              # API client for :8083/api endpoints
└── components/
    ├── DispatchForm.js # Dispatch prompt input
    └── TaskList.js     # Recent dost tasks list
```

## Features

- **Fleet status** — completion rate, error rate, and pools available (from `GET /metrics`)
- **Dispatch prompt** — submit a prompt to the fleet (`POST /tasks/dispatch`)
- **Debate** — start a multi-agent debate (`POST /debates`)
- **Results list** — recent dost tasks (`GET /tasks`)

## Backend

The app talks to the Dost fleet API at `http://127.0.0.1:8083` (see `api.js` `BASE_URL`). The Python SDK lives in `dost/sdk/python/client.py` and documents the same endpoints.

## Getting started

```bash
cd dost/mobile
npm install
npx react-native start      # Metro bundler
npx react-native run-ios    # or run-android
```

> Note: This is a React Native skeleton. For Expo, replace `react-native` with `expo` and adjust the entry point.

## API client (`api.js`)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `getMetrics()` | `GET /metrics` | Fleet status: pools, cooldowns, task counts |
| `dispatchTask(prompt, opts)` | `POST /tasks/dispatch` | Submit a prompt to the fleet |
| `startDebate(prompt, agents?)` | `POST /debates` | Start a multi-agent debate |
| `getTasks()` | `GET /tasks` | List recent tasks |
| `healthCheck()` | `GET /health` | Fleet health |
