# MASTER BUILD PROMPT — OPENALICE UNIVERSAL AI COMMAND CENTER

## Mission

Build a production-quality web dashboard that acts as my universal AI command center.

I want one interface where I can send any prompt, have an AI orchestrator understand it, break it into tasks, delegate work to multiple AI sessions, monitor execution, review results, and approve actions.

The primary AI reasoning engine should connect to OpenAI through the official API. The architecture must also support independently configured AI providers and execution adapters.

This must be a real, functional application — not just a UI mockup, static prototype, or architecture document.

## 1. Core vision

Create a central command center with:

- One universal chat interface.
- One central AI orchestrator.
- Up to 20 coordinated AI sessions initially.
- Dynamic task creation and delegation.
- Agent and session monitoring.
- Persistent project memory and context.
- Approval and permission management.
- Tool and repository integrations.
- Execution logs and audit history.
- Results aggregation and verification.

The system should eventually support thousands of logical agent roles without requiring thousands of simultaneously running processes.

## 2. Dashboard design

Build a polished, modern, responsive dark-mode interface.

Main navigation:

1. Command Center
2. AI Chat
3. Sessions
4. Agents
5. Task Manager
6. Projects
7. Workflows
8. Approvals
9. Integrations
10. Models & Providers
11. Monitoring
12. Cost & Usage
13. Audit Logs
14. Settings

### Command Center

Display:

- Overall system health.
- Active, idle, blocked and failed sessions.
- Active tasks and completion rates.
- Pending approvals.
- Model/provider status.
- API usage and estimated costs.
- Worker availability.
- Recent events.
- Current project activity.

### Universal AI Chat

The chat interface must support:

- Natural-language prompts.
- Long-running tasks.
- Conversation history.
- File attachments.
- Project selection.
- Task execution mode.
- Streaming responses.
- Progress updates.
- Results and downloadable artifacts.
- Approval requests.
- Cancellation and pause controls.

Every prompt must receive a unique ID and be traceable throughout execution.

## 3. AI orchestrator — connect ChatGPT/OpenAI

Integrate the official OpenAI API.

The orchestrator must:

1. Receive a user prompt.
2. Retrieve relevant project context.
3. Understand the requested outcome.
4. Determine whether the task needs tools or delegation.
5. Produce a structured execution plan.
6. Break work into bounded tasks.
7. Assign tasks to appropriate sessions.
8. Monitor execution.
9. Validate returned evidence.
10. Present a consolidated result to me.

Use supported OpenAI APIs and documented authentication methods.

Do not assume that a ChatGPT subscription automatically provides API access. API credentials and billing must be configured separately.

Never expose API keys in frontend code, browser storage, Git, prompts, logs or reports.

Implement model configuration through secure server-side settings.

Support model selection, context limits, timeouts, usage tracking and configurable budgets.

Do not hardcode a model name throughout the application.

## 4. Twenty-session coordination

Create a session orchestration framework supporting 20 initial session slots.

Suggested responsibilities:

01. Chief Orchestrator
02. Repository & Ownership Auditor
03. Session Coordinator
04. Architecture Engineer
05. Role Registry Engineer
06. Task-State Engineer
07. Scheduler & Queue Engineer
08. Budget & Quota Engineer
09. Lease & Lifecycle Engineer
10. Runtime Isolation Engineer
11. Runtime Adapter Engineer
12. Provider Governance Engineer
13. Verification Engineer
14. Event & Outbox Engineer
15. Security & Policy Engineer
16. Data & Artifact Engineer
17. Monitoring Engineer
18. QA Engineer
19. Integration Engineer
20. Independent Auditor

These are logical responsibilities, not assumptions that 20 sessions already exist.

The coordinator must discover available sessions and adapters before assigning work.

Each session must have:

- Unique session ID.
- Assigned role.
- Provider and model.
- Current status.
- Current task.
- Repository/worktree.
- Permission scope.
- Start and completion timestamps.
- Execution logs.
- Results and evidence.
- Error and retry history.

Never pretend a session is active when it is not.

Never restart archived or stopped sessions without authorization.

Prevent multiple sessions from modifying the same files concurrently.

## 5. Task orchestration

Implement a persistent task engine.

Each task must include:

- Unique task ID.
- Parent prompt ID.
- Objective.
- Assigned session.
- Dependencies.
- Priority.
- Exact repository and worktree.
- Base commit.
- Allowed files and paths.
- Allowed operations.
- Prohibited operations.
- Acceptance criteria.
- Verification requirements.
- Time and resource limits.
- Current status.
- Execution evidence.

Task lifecycle:

CREATED → PLANNED → APPROVED → QUEUED → RUNNING → VERIFYING → COMPLETED

Additional states:

BLOCKED, FAILED, CANCELLED, QUARANTINED.

Support retries only when policy permits them.

The task-state authority must be the sole writer of task transitions.

Use transactional state changes, fencing tokens, lease validation and an atomic outbox pattern.

## 6. Execution adapters

Create modular adapters for:

- OpenAI API.
- Codex, where an authorized integration is available.
- OpenCode sessions.
- Other explicitly configured model providers.
- Local test runners.
- Sandboxed code execution.
- Git repositories.

Do not assume that an installed application automatically exposes an API.

Discover available integration methods and document their actual capabilities.

Adapters must report whether they can read, write, execute, test or merely provide responses.

Keep provider configuration separate from worker execution configuration.

### Provider policy

For existing OpenAlice worker workloads, preserve NVIDIA-only and fail-clear requirements.

Do not introduce Anthropic paid fallback or OpenRouter.

OpenAI is a separately approved dashboard reasoning integration, not an automatic replacement for NVIDIA worker inference.

No silent model switching or fallback.

## 7. Repository and development workflow

Before implementing:

1. Discover the available repositories.
2. Identify canonical ownership and repository paths.
3. Inspect current branches and dirty working trees.
4. Identify existing services, APIs and integrations.
5. Inspect existing architecture and documentation.
6. Identify conflicts and dependencies.
7. Produce a task and implementation map.

Create the dashboard in a new isolated project or dedicated worktree.

Do not overwrite existing OpenAlice projects.

Preserve all dirty and untracked work.

Never use destructive Git commands, force-push, or automatic merges.

Use isolated branches and require human review.

Do not change existing HUD deployment, launchd services, trading configuration or live infrastructure as part of dashboard development.

## 8. Technology architecture

Evaluate and implement a maintainable stack:

Frontend:
- Next.js.
- React.
- TypeScript.
- Responsive component system.
- Real-time status updates.

Backend:
- Python FastAPI.
- REST APIs.
- WebSockets.
- Authentication and authorization.

Persistence:
- PostgreSQL for durable application state.
- Redis for transient queues and coordination, if justified.
- Durable artifact storage.

Execution:
- Isolated cloud workers.
- Sandboxed execution environments.
- Explicit tool permissions.

Infrastructure:
- Containerized services.
- Health checks.
- Structured logging.
- Monitoring.
- Backup and recovery.

Document the final architecture and explain any deviations.

## 9. Security and approval center

Implement role-based permissions and explicit approvals.

Classify actions:

A. Read-only operations.
B. Approved reversible local engineering.
C. Destructive or broad operations.
D. External or paid side-effect operations.
E. Protected infrastructure or trading operations.

C, D and E must remain blocked until separately authorized.

Require approval for:

- External API actions with side effects.
- Paid operations beyond approved budgets.
- File deletion.
- Git push, merge or release.
- Cloud provisioning.
- Production deployment.
- Credential or permission changes.
- Trading configuration changes.

Approval must be tied to the exact action, target and scope.

Never treat a general instruction as blanket authorization.

## 10. OpenAlice-specific protections

Preserve these invariants:

- NVIDIA-only worker inference.
- Fail-clear provider behavior.
- No Anthropic paid fallback.
- No OpenRouter.
- No secrets in Git, prompts or logs.
- Trading remains PAPER-only.
- Trading kill switch remains locked.
- No live trading or TESTNET-to-LIVE transition.
- No unauthorized HUD changes.
- No unauthorized launchd or service changes.
- No automatic cloud deployment.
- No public synchronization.

Keep the dashboard separate from the trading execution system.

The dashboard must not gain trading credentials or direct trading execution permissions.

## 11. Observability

Provide:

- Live session status.
- Task progress.
- Worker health.
- API latency.
- Token consumption.
- Estimated costs.
- Failed requests.
- Retry counts.
- Error traces.
- Audit records.
- Provider availability.
- Queue depth.
- Resource consumption.

Make it possible to trace a user prompt through every task, session, tool invocation and final result.

## 12. Testing and acceptance

Build automated tests for:

- Authentication.
- Prompt submission.
- Conversation persistence.
- AI API integration.
- Session creation and status.
- Task delegation.
- Dependency handling.
- Concurrent execution.
- Lease expiry.
- Fencing tokens.
- Task-state consistency.
- Cancellation.
- Retry behavior.
- Approval enforcement.
- Provider failure.
- Secret redaction.
- Audit logging.
- WebSocket updates.
- Recovery after restart.

Use mock providers and synthetic data for offline tests.

Do not spend money or call external services during tests without separate approval.

## 13. Implementation sequence

Wave 1 — Discovery:
- Inspect available repositories and integrations.
- Confirm project ownership.
- Establish isolated development environment.
- Produce implementation task cards.

Wave 2 — Foundation:
- Backend.
- Frontend.
- Database.
- Authentication.
- Prompt and conversation management.

Wave 3 — AI integration:
- OpenAI API.
- Model configuration.
- Orchestrator.
- Structured plans.
- Streaming responses.

Wave 4 — Session management:
- Session registry.
- 20 logical session slots.
- Adapter interfaces.
- Task engine.
- Delegation and coordination.

Wave 5 — Dashboard:
- Command Center.
- Chat.
- Agent and session pages.
- Task manager.
- Approval center.
- Monitoring and audit logs.

Wave 6 — Verification:
- Integration tests.
- Security tests.
- Failure simulations.
- Performance tests.
- Independent audit.

Wave 7 — Review:
- Produce a working local demonstration.
- Document installation and configuration.
- Provide screenshots and test evidence.
- Prepare a deployment proposal separately.

## 14. Definition of done

The first release is accepted only when:

1. I can open the dashboard in a browser.
2. I can submit a prompt.
3. The configured OpenAI model returns a response.
4. Conversations persist after restart.
5. The orchestrator can create structured tasks.
6. Tasks can be assigned to available sessions.
7. I can see session and task status live.
8. Results can be collected and consolidated.
9. Approval gates actually block unauthorized actions.
10. Audit logs show what happened.
11. Provider failures are handled safely.
12. Automated tests demonstrate the critical functionality.

Do not mark simulated features as implemented.

Clearly distinguish:
- Implemented.
- Locally tested.
- Integration tested.
- Human reviewed.
- Deployed.
- Production verified.

## 15. Required working behavior

Do not respond with another architecture proposal alone.

Start with read-only discovery, then identify independent implementation tasks and execute the bounded work that is authorized.

If blocked, report the exact blocker and continue with independent permitted work.

Do not invent repository paths, session IDs, credentials, integrations, test results or deployment status.

Do not deploy or modify protected systems.

At completion, provide:

- Repository and branch.
- Implemented components.
- Changed file list.
- Commands executed.
- Test results and exit codes.
- API integration status.
- Available session adapters.
- Outstanding limitations.
- Security findings.
- Human approvals still required.
- Exact next action.

**Final objective: Build a real universal AI command center where I can send one prompt, coordinate multiple AI sessions, supervise execution and receive verified results from one dashboard.**