# Task Card S04 — Architecture and contracts

Task ID: S04-001
Responsible session: S04
Objective: Architecture-to-implementation traceability matrix for OpenAlice 10K
Repository: /Users/aryanagarwal/openalice-fleet
Base commit: 5d7603151060851970f65136e32036e89b027726
Allowed dirs: docs/, reports/
Forbidden dirs: services/, runtime/, tools/
Permitted ops: read-only, documentation creation
Prohibited ops: code changes, commits, pushes
Dependencies: S01, S02
Acceptance criteria:
- Traceability matrix file exists at docs/traceability/S04-matrix.md
- Matrix covers Role registry, Task-state authority, Budget authority, Scheduler, Runtime isolation
- Each row references architecture section and implementation evidence or explicit "design-only"
Tests: static file existence check
Evidence required: matrix file, git log showing no changes to forbidden dirs
Stop conditions: repository ownership unresolved, protected path access requested
