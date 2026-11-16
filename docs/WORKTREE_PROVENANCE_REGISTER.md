# OpenAlice Fleet – Worktree Provenance Register
Generated: 2026-10-31
Repo: /Users/aryanagarwal/openalice-fleet
Section 20: read-only inventory

## Git Worktree List

| Worktree Path | Commit | Branch / State |
|---|---|---|
| /Users/aryanagarwal/openalice-fleet | df02580 | [main] |
| /private/var/folders/z0/rp2twm2n4n7_q7chsbt22vz00000gn/T/opencode/wt-mergetest | c475f9d | (detached HEAD) |
| /private/var/folders/z0/rp2twm2n4n7_q7chsbt22vz00000gn/T/opencode/wt-watchdog | 16c62bf | [agent/pipeline-verify/watchdog-py39-import-fix] |
| /Users/aryanagarwal/fleet-worktrees/cred-gates-20261024 | 0e06c5b | [qoder/credential-shape-gates] |
| /Users/aryanagarwal/fleet-worktrees/hud-session-truth | cbc649f | [qoder/hud-session-truth] |
| /Users/aryanagarwal/fleet-worktrees/office-deploy | a33d621 | (detached HEAD) |
| /Users/aryanagarwal/fleet-worktrees/office-hive-agents | c0ed413 | [qoder/hive-agent-sessions] |
| /Users/aryanagarwal/fleet-worktrees/office-sessions | 0c02512 | [qoder/office-sessions] |
| /Users/aryanagarwal/fleet-worktrees/office-work-view | 93345b3 | [qoder/office-work-view] |
| /Users/aryanagarwal/fleet-worktrees/sync-reroster | 2b5dda5 | [sync/reroster] |
| /Users/aryanagarwal/openalice-fleet/.worktrees/arming-residual | b91f282 | [qoder/sma-arming-residual] |
| /Users/aryanagarwal/openalice-fleet/.worktrees/cherry-local | 7e90c1d | (detached HEAD) |
| /Users/aryanagarwal/openalice-fleet/.worktrees/hud-bounded-launcher-14b07adc | 39314e2 | (detached HEAD) |
| /Users/aryanagarwal/openalice-fleet/.worktrees/installed-plist-audit | a34e8b6 | [qoder/installed-plist-audit] |
| /Users/aryanagarwal/openalice-fleet/.worktrees/installed-plist-audit-v2 | c8e133e | [qoder/installed-plist-audit-v2] |
| /Users/aryanagarwal/openalice-fleet/fleet-worktrees/ui-fleet-page | 96f021f | [ui/fleet-health-page] |

## Session-to-Worktree Mapping
Status: INCOMPLETE

- Current opencode session metadata exposes `location.directory` only at project root `/Users/aryanagarwal`.
- No worktree-specific cwd is surfaced via `opencode session list` or `opencode api get /api/session/<id>`.
- Mapping requires deeper metadata: session working directory at creation/move time, or session ↔ worktree binding logs.

## Provenance Notes
- Canonical repo: openalice-fleet, main at df02580 converged to origin/main 7e90c1d after watchdog fix.
- Worktrees under `/Users/aryanagarwal/fleet-worktrees/` and `.worktrees/` are isolated for bounded reversible changes per Section 20.
- `fleet-worktrees/` is untracked in git per policy.

## Evidence Sources
- `git -C /Users/aryanagarwal/openalice-fleet worktree list`
- `opencode session list --format json`
- Generated 2026-10-31
