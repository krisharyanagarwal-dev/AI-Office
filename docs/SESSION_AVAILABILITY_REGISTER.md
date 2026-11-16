# OpenAlice 10K Office – Session Availability Register
Generated: 2026-10-31
Scope: 20 sessions for OpenAlice 10K Office per Section 20 read-only discovery

## Cohort Summary
- ORG sessions: 10
- Dashboard sessions: 8 (6 core + 2 verification)
- Office sessions: 2
- Total registered: 20

## Session Details

| Session ID | Title | Outcome | Agent | Model | Updated (epoch ms) | Directory | Status |
|---|---|---|---|---|---|---|---|
| ses_e7154cea4ffeZMxKXbcsgnMs1R | ORG-LEAD-ENG | succeeded | build | meta/muse-glimmer-30b | 1793459181385 | /Users/aryanagarwal | active |
| ses_e7154cbeaffeeWFEVTbNGY7cAc | ORG-W-ENG-2 | succeeded | build | nemotron-3.5-bolt-e4b | 1793443582821 | /Users/aryanagarwal | active |
| ses_e7154cf44ffeGIeV1tQUS3p8aA | ORG-CEO | succeeded | build | nemotron-3.5-bolt-e4b | 1793443569350 | /Users/aryanagarwal | active |
| ses_e7154cc9dffe2sGxaxOL7nvV8C | ORG-W-ENG-1 | succeeded | build | nemotron-3.5-bolt-e4b | 1793443542209 | /Users/aryanagarwal | active |
| ses_e7154c9cfffewKpcfptBJmi1iz | ORG-W-OPS-1 | succeeded | build | nemotron-3.5-bolt-e4b | 1793443070863 | /Users/aryanagarwal | active |
| ses_e7154c8a3ffe24ZJ8BdDN1Y1mH | ORG-W-OPS-2 | succeeded | build | nemotron-3.5-bolt-e4b | 1793443060124 | /Users/aryanagarwal | active |
| ses_e7154cd53ffemh0cj1oa20XEtB | ORG-LEAD-OPS | succeeded | build | nemotron-3.5-bolt-e4b | 1793442993518 | /Users/aryanagarwal | active |
| ses_e7154ca7fffeVQHKN1fktj0JRq | ORG-W-RSRCH-2 | succeeded | build | qwen2.5:0.5b | 1793442986807 | /Users/aryanagarwal | active |
| ses_e7154cb34ffexACOXvf8jQwEFu | ORG-W-RSRCH-1 | succeeded | build | qwen2.5:0.5b | 1793415067945 | /Users/aryanagarwal | active |
| ses_e7154ce09ffeLNVB7kFag12B6j | ORG-LEAD-RSRCH | succeeded | build | qwen2.5:0.5b | 1793395855589 | /Users/aryanagarwal | active |
| ses_e72534e77ffeDosBpGv0V4Uz4k | Dashboard - Fleet Monitor | failed | build | nemotron-3.5-bolt-e4b | 1793461708607 | /Users/aryanagarwal | failed |
| ses_e72534efcffeRPqt7MGjpkumkg | Dashboard - API Server | succeeded | build | meta/muse-glimmer-30b | 1793459126332 | /Users/aryanagarwal | active |
| ses_e72534e21ffeGvFXsSnCDMApso | Dashboard - Config Manager | succeeded | build | qwen2.5:0.5b | 1793401783585 | /Users/aryanagarwal | active |
| ses_e72534e4cffeBY41pa1RScRRLD | Dashboard - Alert Engine | succeeded | build | qwen2.5:0.5b | 1793396669825 | /Users/aryanagarwal | active |
| ses_e72534ecdffe4HxOnXA6SXEGGv | Dashboard - Web UI | succeeded | build | qwen2.5:0.5b | 1793394876380 | /Users/aryanagarwal | active |
| ses_e72534ea2ffe6XCZ3patjE1KzS | Dashboard - Metrics Collector | succeeded | build | qwen2.5:0.5b | 1793394876032 | /Users/aryanagarwal | active |
| ses_e6dce7d32ffexI3HjAl0pUkOST | Dashboard endpoint verification | failed | N/A | nemotron-3-ultra-550b-a55b | 1793458998367 | /Users/aryanagarwal | failed |
| ses_e6e3cb65effeCEN3QCl2HDS3LU | Dashboard endpoint verification | succeeded | N/A | meta/muse-glimmer-30b | 1793457277098 | /Users/aryanagarwal | active |
| ses_e73142511ffei0VhzfGyHbQZw5 | Office tasks | succeeded | build | qwen2.5:0.5b | 1793394815854 | /Users/aryanagarwal | active |
| ses_e7311cc51ffe4QKrQ250Jc0dNl | Office - session foreman | failed | N/A | N/A | 1793376316051 | /Users/aryanagarwal | failed |

## Classification
- Active / succeeded: 16
- Failed: 4
- All sessions report directory /Users/aryanagarwal; worktree-specific cwd not exposed via current API.

## Notes
- Model routing is NVIDIA-only per policy; observed models: meta/muse-glimmer-30b, nemotron-3.5-bolt-e4b, qwen2.5:0.5b, nemotron-3-ultra-550b-a55b.
- Cost is 0 for all sampled sessions.
- Session-to-worktree ownership mapping requires deeper metadata beyond `location.directory`. Blocked pending session cwd / worktree binding discovery.

## Evidence Sources
- opencode session list --format json
- opencode api get /api/session/<id>
- Generated 2026-10-31
