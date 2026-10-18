# Recall — Real Feature Implementation Plan

> **For agentic workers:** Execute task-by-task inline, keeping live search and approved execution compatible. This plan supersedes 2026-10-17-reference-redesign.md. No demo mode or fabricated product data.

**Goal:** Implement every reference page with real persisted data, real backend operations, and the supplied blue/lavender visual design.

**Architecture:** React/TypeScript frontend with reusable components, typed API client and stable navigation. FastAPI owns durable workflows, recording sessions, discovery jobs, schedules, settings and execution; Screenpipe MCP remains the historical source and Zavora remains the live desktop executor. Use atomic local JSON initially, one server worker, and explicit service lifecycles; SQLite is not required for this scope.

**Tech Stack:** Existing React, TypeScript, Vite, Lucide, FastAPI, Pydantic, MCP, Azure/OpenAI, Zavora. Python zoneinfo for recurrence; a small Windows hotkey helper for actual global shortcuts. Add dependencies only where a concrete implementation needs them.

**Spec:** C:/Users/Doffa/.codex/attachments/7e388e80-6373-4619-afbe-bf1b9ff70b44/Pasted text.txt and seven attached images.

## Mandatory delivery rules

- No mock data, demo timers, fabricated schedules, made-up confidence, repetition counts, app status, screenshots, attachments or verification.
- Every enabled control performs a real operation and survives restart when appropriate.
- Empty data produces an honest empty state; upstream failures produce actionable errors.
- Never auto-select a memory. Preserve distinct occurrences even when grouped as related workflows.
- Historical evidence is untrusted data, never instructions. Preserve verbatim quotes and provenance.
- Separate historical steps, user edits and planned current actions.
- Missing/masked values remain explicit; do not guess them.
- Every desktop mutation requires a fresh explicit approval; scheduled runs preserve this rule.
- Stop prevents future actions and explains that completed changes are not undone.
- Completion is tied to actual live verification after the last mutation.
- No API keys in frontend responses/logs. Relevant context may be sent to the configured provider; describe that honestly.
- Match the references with reusable CSS/SVG waves, stable sidebar, light cards, indigo controls and responsive details.
- Keep existing endpoints compatible. Introduce new routes rather than changing existing response shapes unexpectedly.
- Support one local backend process. Do not claim execution while the PC/server is off or the desktop is locked.

## Current implementation audit

Working backend: /health; /tasks; /tasks/search; /tasks/{id}/workflow; /tasks/{id}/reconstruct; /tasks/{id}/execute; /runs; /runs/{id}; /runs/{id}/approval; /runs/{id}/stop; /desktop/apps.

Current task retention is one hour with a 200-item cap. Runs persist as JSON; execution already enforces approval and verification. /health checks configuration/prerequisites, not live Screenpipe/model/desktop readiness.

Missing: durable independent workflow library, recorded segments, processing jobs, workflow editing, evidence-backed grouping, recurrence scheduler, real settings controls, actual connection checks and global hotkeys. New UI files have been started but are not a completed or shipped redesign; finish and verify them after the backend contracts below are implemented.

Inspected Screenpipe tool schemas in docs/mcp-tools.json include health-check, activity-summary, search-content, frame-context, keyword-search, get-frame-elements, list-workflows and get-workflow. Re-inspect actual tool schemas when implementing. control-recording explicitly starts/stops AUDIO only, not screen capture. Do not use it as a workflow recording switch. No proven capture-settings write API is established yet.

## Implementation order

1. Durable data and capability APIs.
2. Shared UI shell, real Home and Memories.
3. Workflow review, durable library, live Runs/approval.
4. Real bounded workflow recording and reconstruction.
5. Evidence-backed repeated-task discovery.
6. Persistent scheduling and due-run handling.
7. Real Settings, notifications and global shortcuts.
8. Complete visual verification, integration tests and real timed acceptance tests.

## 1. Durable records, jobs and capabilities

**Files:** backend/models.py, repository.py, main.py; new backend/workflow_store.py, jobs.py, capabilities.py; frontend/src/types.ts, api.ts.

- [ ] Define versioned Pydantic models: SavedWorkflow, WorkflowRevision, RecordingSession, RecordingMarker, InvestigationJob, WorkflowGroup, ScheduleRecord, ScheduleOccurrence, UserPreferences and CapabilityStatus.
- [ ] SavedWorkflow stores original task snapshot, evidence ledger, reconstruction, editable run defaults, revision and timestamps. Preserve the original historical reconstruction separately from edits.
- [ ] Persist workflows independently of expiring search tasks, with atomic writes and serialized mutations. Never rely on browser state for saved workflows or schedules.
- [ ] Persist jobs and active sessions; mark interrupted work on restart. Keep recoverable failure details without secrets.
- [ ] Add GET /capabilities returning supported/unsupported/error state, last checked time and explanation for each integration. Do not infer readiness from an installed executable.
- [ ] Extend typed client to GET/POST/PATCH/DELETE and typed HTTP errors. Distinguish a missing workflow (404) from connection/model failures.
- [ ] Add service initialization/shutdown in FastAPI lifespan; preserve local-origin protection on all new writes.

**Acceptance:** Save/reload workflow after task expiration and server restart; conflicting revisions return 409; corrupted JSON surfaces an error; interrupted jobs do not silently resume desktop actions.

## 2. App shell and Home

**Files:** frontend/src/components.tsx, App.tsx, styles.css; new shell/navigation module as needed.

- [ ] Implement all seven sidebar destinations in the reference order, keyboard focus, responsive collapse, consistent logo/workspace/connection card.
- [ ] Use hash routes or real routes with an explicit FastAPI fallback; every destination must survive refresh and browser back/forward.
- [ ] Home has the reference hero, real search, four prompt shortcuts, three quick-start cards and only three recent-work cards.
- [ ] GET /tasks supplies discovered occurrences; GET /workflows supplies durable recent workflows. Use actual timestamps and source metadata only.
- [ ] Connection card reflects backend reachability; Screenpipe/model/desktop health stays distinct in Settings.
- [ ] Quick-start actions navigate to implemented search, recording and schedule forms.

**Acceptance:** Search submits on Enter; real recent items open the chosen occurrence; no seeded example email/report cards; Home has no crowded detail sidebar.

## 3. Memories and evidence

**Files:** backend/models.py, agent.py, screenpipe_tools.py, main.py; frontend/src/memory-pages.tsx, components.tsx.

- [ ] Preserve POST /tasks/search behavior; add optional structured date/source filters without breaking message-only clients.
- [ ] Resolve Today/Yesterday/This week in the configured IANA timezone and pass exact bounds to MCP searches. Filters are applied server-side, not merely keyword chips.
- [ ] Keep iterative tool selection, contextual retrieval, refinement and pagination. Record searched interval, coverage and upstream failures so an empty list is not treated as proof of no activity.
- [ ] Add optional evidence metadata only when present: frame/source ID, recorded timestamp, app/window, URL. Keep exact quotes and source_kind.
- [ ] Render distinct result cards, sorting, elapsed search time, explicit selection, selected outline and original evidence panel.
- [ ] Do not add confidence percentages/badges unless a defined backend evidence assessment exists; show original-activity/support status instead.
- [ ] Show attachments/open-source links only when actually recovered; validate URL schemes and never invent links from titles.
- [ ] Provide source expansion, copy link where real source links exist, friendly empty/error states and expired-result recovery.

**Acceptance:** Real email/Notepad searches; two similar occurrences stay distinct; none selected automatically; date boundaries are correct; discussion-only evidence is visibly differentiated.

## 4. Workflow review and saved library

**Files:** new backend/workflows.py, workflow_store.py; backend/main.py, models.py, execution.py; frontend/src/memory-pages.tsx.

**API contracts:**
- POST /workflows {task_id,title?,defaults?} -> SavedWorkflow, copying verified reconstruction and ledger.
- GET /workflows and GET /workflows/{id} -> durable records.
- PATCH /workflows/{id} {expected_revision,title?,run_defaults?,user_notes?} -> new revision.
- DELETE /workflows/{id} -> archive after handling dependent schedules explicitly.
- POST /workflows/{id}/execute -> RunRecord using pinned workflow revision and reviewed overrides.

- [ ] Keep existing task reconstruction and task execution compatible.
- [ ] Build two-column review with selected memory, stage bar, historical steps/evidence, editable values, missing values and target instructions.
- [ ] Add Save workflow, rename, archive and reopen operations backed by APIs.
- [ ] Permit annotations/desired-run edits without rewriting historical observations as facts.
- [ ] Disable execution until required gaps are answered; backend validates readiness as well as frontend.
- [ ] Review every saved workflow before a new run; Run on cards opens review, never silently executes.
- [ ] Show last real run, actual status and user-defined tags; no fabricated categories or repeat counts.

**Acceptance:** Save, restart, reopen, edit defaults, compare original value, and run a workflow whose original search task has expired. No reconstruction is triggered again merely because a saved read failed with a network error.

## 5. Live execution, approvals and Runs

**Files:** backend/execution.py, models.py, main.py; new frontend/src/run-pages.tsx.

- [ ] Preserve existing per-action inspection, approval tokens, fresh target identity, ambiguity rejection and verify-after-mutation checks.
- [ ] Add structured user-facing event categories/messages while retaining raw diagnostic payloads in expandable Details.
- [ ] Approval shows readable target window, intended action, exact new value, reason and workflow source. Tool names/window IDs/roles appear only under Details.
- [ ] Runs page has current run, actual event timeline, actual timestamps/durations, filters/search and detail drawer with Overview/Step details.
- [ ] Use actual completed observations and status. Avoid fixed-step percentages when execution can branch; use indeterminate activity plus observed counts unless a real denominator exists.
- [ ] Display verification success only from verified backend events and final completed state. Include the actual verified property/value, not generic assumed success.
- [ ] Active run survives navigation and browser refresh; GET /runs finds it and polling resumes.
- [ ] Stop remains visible, with clear irreversible-change explanation. Approval/decline handles stale tokens and network failures without duplicate actions.

**Acceptance:** Real isolated Notepad change, approval then fresh verification; decline causes no mutation; stop halts further work; ambiguous targets block; refresh during approval restores the exact pending action.

## 6. Real workflow recording — timestamp bookmarks only

**User clarification:** Start saves a server-side start timestamp. Stop saves a server-side end timestamp. The custom agent queries existing Screenpipe history strictly between those timestamps to identify the performed work and reconstruct a reviewable workflow. Recall does not start/stop capture, install input hooks, or control Screenpipe recording. Step markers are optional timestamp bookmarks, not captured input events.

**Files:** new backend/recordings.py; models.py, main.py, jobs.py; frontend/src/support-pages.tsx or separate recording page.

**API contracts:**
- POST /recordings/start {title?} -> RecordingSession, with server timestamp and initial capture health.
- POST /recordings/{id}/markers {label?} -> real timestamped marker.
- POST /recordings/{id}/stop -> ended session and processing job.
- GET /recordings, GET /recordings/{id}, GET /jobs/{id}.
- POST /recordings/{id}/retry-processing -> bounded retry job.

- [ ] Save the start bookmark immediately and check Screenpipe health without delaying the timestamp. If Screenpipe is unavailable, retain the interval and explain that history may be missing; allow retry after stop. Never claim Recall itself is capturing activity.
- [ ] Start marks a real interval in continuously recorded history, not a separate recorder and not audio control-recording.
- [ ] Persist start/end and markers server-side; restore timer from timestamps after reload. Allow only one active recording segment.
- [ ] Stop fixes the interval, retrieves real activity-summary and paginated sources in those exact bounds through MCP, and accounts for capture ingestion delay with bounded retries.
- [ ] Reconstruct a single workflow from that segment using original evidence. Mark unavailable clicks/typing/path details missing; do not claim every input was captured.
- [ ] Show processing job status, actual gaps and recoverable error. No screenshots/step totals before evidence exists.
- [ ] Open review as a draft; save only after user review. Last captured card comes from the recorded session/workflow API.
- [ ] Start/stop changes only Recall's marked segment; never pauses Screenpipe's global screen recorder.

**Acceptance:** Start, perform a fresh short Notepad task, add a marker, stop, reconstruct from that actual interval, inspect quotes and edit/save. Test recorder offline, ingestion delay, empty interval, browser reload and backend restart.

## 7. Real workflow discovery and repeat counts

**Files:** new backend/discovery.py; jobs.py, agent.py, models.py, main.py; frontend workflow page.

**API contracts:** POST /workflows/discover {start_time,end_time}; GET /workflow-groups; GET /workflow-groups/{id}.

- [ ] Inspect list-workflows/get-workflow dynamically for usable original catalog evidence; they are read-only inputs, not permission to run Screenpipe Pi or delegate reasoning to it.
- [ ] Custom agent investigates a bounded interval via activity-summary and source evidence, then proposes related workflow groups with member occurrence references.
- [ ] Validate each member against original evidence; deduplicate repeated frames of the same occurrence before counting.
- [ ] Keep task occurrences individually addressable, even when related. Grouping never auto-selects a representative for execution.
- [ ] Display observed occurrence count and covered interval, not a guessed weekly frequency or claims of exhaustive coverage.
- [ ] Show incomplete coverage/uncertain grouping explicitly; allow inspect members and remove a wrong association.
- [ ] Suggestions, Most repeated and Saved tabs use actual groups/library data and real search/filtering.

**Acceptance:** A bounded real dataset produces individually inspectable groups/counts; count equals validated distinct members; discussion mentions do not inflate counts; no activity yields an honest empty state.

## 8. Persistent scheduling

**Files:** new backend/scheduler.py, schedule_routes.py; models.py, main.py, workflow_store.py; frontend schedule page.

**API contracts:** GET/POST /schedules; PATCH/DELETE /schedules/{id}; GET /schedules/{id}/occurrences. Each record includes workflow revision, once/daily/weekly/monthly rule, local time/date, IANA timezone, enabled, next_run_at and notification preference.

- [ ] Implement validated recurrence calculations in UTC from local wall times, with a documented DST and month-end policy. Show exact next occurrence before saving.
- [ ] Support actual create/edit/delete, pause/resume and sorted upcoming items; edit reuses the same validated form.
- [ ] Persist due occurrence keys and run linkage before dispatch to prevent duplicates; serialize scheduling mutations.
- [ ] Scheduler runs in FastAPI lifespan, resumes future jobs on startup and records missed jobs. Default: mark missed occurrences, no surprise catch-up desktop actions.
- [ ] Scheduled execution uses the same ExecutionManager and pinned workflow revision; every mutation still waits for explicit approval. Notify the user when approval is needed.
- [ ] Busy desktop: record delayed/blocked occurrence with clear expiry; do not launch concurrent execution. Locked/unavailable desktop blocks execution; never invent readiness.
- [ ] Deleting/archiving a workflow pauses dependent schedules with explanation; edits do not silently swap a scheduled revision.
- [ ] UI states clearly that local server, PC and an interactive desktop must be available; approval may be required at run time.

**Acceptance:** Real near-term one-time schedule fires exactly once and reaches approval; daily/weekly/monthly calculations and DST boundaries pass focused tests; restart does not duplicate; pause/delete prevent dispatch; missed and blocked occurrences are visible.

## 9. Real settings and integration checks

**Files:** new backend/preferences.py, integration_status.py; config.py, main.py; frontend settings page.

**API contracts:** GET/PATCH /settings for approved non-secret preferences; POST /connections/{screenpipe|model|desktop}/test; GET /system/status for real disk free bytes and data directory metadata.

- [ ] Local connection/storage comes from actual server and disk measurements.
- [ ] Screenpipe status calls actual MCP health-check. Capture settings require discovery of a supported installed-version management API; validate each control by reading back the changed state. If none exists, build a real Open Screenpipe settings action rather than a toggle that does nothing.
- [ ] Keep capability-dependent capture controls out of the active form until the native capability exists. Explain exactly which capture settings are managed in Screenpipe.
- [ ] Model test performs a minimal real provider request with timing; configured is not the same as connected. Show actual provider/deployment from sanitized config.
- [ ] Provider/model editing uses backend validation and an atomic config override store; never return existing secrets. A replacement key is write-only and masked; avoid logging request bodies. Retain environment fallback.
- [ ] Desktop test performs real window enumeration, not executable presence.
- [ ] Desktop permission toggle must actually gate all new executions and pending mutations in ExecutionManager. Disabling it cancels/stops active work consistently; re-enabling never grants approval to a pending action automatically.
- [ ] Appearance implements light/dark/system and accent changes throughout all pages, persists preference and respects reduced motion.
- [ ] Notification toggles route real run/approval/schedule notifications. Ask for browser notification permission only on explicit enable; show in-app fallback if unsupported. No fake product-update subscription.
- [ ] Privacy copy explains local storage and relevant-context transmission to the configured model.

**Acceptance:** Provider failures are visible, disk numbers match system readings, capture controls read back real state, permission disable blocks mutations, themes apply after restart, keys never appear in responses.

## 10. Global shortcuts and real notifications

**Files:** new backend/hotkeys.py, notifications.py; main.py, preferences.py; frontend recording/settings components.

- [ ] Implement Windows RegisterHotKey in a lifecycle-managed message-loop helper, using configurable combinations and reported registration failures.
- [ ] Ctrl+Shift+R calls real recording start/stop; Ctrl+Shift+M creates a marker only during an active session.
- [ ] Open Recall/search shortcut opens/focuses the local app where supported. Run-last shortcut opens the actual latest saved workflow review; it does not bypass review/approval.
- [ ] Publish hotkey actions through persisted session state or an event stream; browser UI refreshes from backend truth.
- [ ] Prevent duplicate registrations under reload/multiple helpers; unregister on shutdown. Show conflicts honestly.
- [ ] Real run/approval/schedule notifications use discovered supported notification capabilities with confirmed delivery or explicit fallback.

**Acceptance:** Shortcuts work while Notepad is focused, create real markers, restore UI state, and never bypass desktop approval. A shortcut conflict shows an actionable status.

## 11. Visual and interaction completion

**Files:** frontend/src/components.tsx, styles.css and per-feature pages.

- [ ] Match reference structure at desktop width: 210px sidebar, large wave hero, generous white cards, indigo gradients, rounded filters, split evidence/review/schedule layouts and run drawer.
- [ ] Build reusable shell/header/search/chips/cards/badges/evidence/fields/toggle/tabs/dialog/drawer/toast/record controls from actual feature contracts above.
- [ ] Use native accessible date/time/select controls unless custom behavior is necessary.
- [ ] Keyboard navigation, named controls, focus trapping/restoration, visible focus and screen-reader live statuses.
- [ ] Subtle page/card/approval transitions, recording pulse and indeterminate run animation; honor reduced-motion preferences.
- [ ] At narrow widths collapse sidebar labels and stack content; details become accessible dismissible drawers.
- [ ] No enabled dead overflow menus, fake links, cosmetic toggles, fixed sample rows or decorative search controls.

**Acceptance:** Inspect all seven real pages, workflow review and live approval at desktop/tablet/mobile widths; no clipped controls or horizontal overflow; no console errors.

## 12. Test and delivery gates

- [ ] Preserve existing backend tests and add focused tests for durable revisions, recording boundaries/markers, evidence grouping, recurrence/DST, restart recovery, settings gating and duplicate prevention.
- [ ] Production TypeScript/Vite build passes; full backend suite passes.
- [ ] Exercise frontend against real local APIs: search, select, reconstruct, edit, save, reopen, start run, approve, verify, inspect history.
- [ ] Record one real new Notepad workflow; confirm retrieved evidence belongs to the selected interval.
- [ ] Create one near-term real schedule against that isolated test document; approve its change and verify completion; remove the temporary schedule afterward.
- [ ] Validate global shortcuts from another focused app and real connection tests.
- [ ] Capture measured end-to-end search/reconstruction/record-processing/run/schedule times. Separate human approval delay from agent execution where possible.
- [ ] Use safe isolated test documents. Never test send/delete/overwrite against the user's original historical targets.
- [ ] Save private evidence/timings under ignored artifacts/ and concise non-secret verification in docs/verification.md.
- [ ] Update README/setup/.env.example for new services, permissions, single-process scheduler and restart behavior.

## Definition of done

Each page is backed by actual API data and functional controls. Recording produces a real evidence-backed reviewable workflow. Saved workflows survive expiration/restart. Repetition counts link to actual distinct occurrences. Schedules produce real runs without bypassing approval. Settings reflect and change real supported behavior. The complete recall → explicit selection → review → approved replay → verified result flow remains working and visually matches the references.



## Implementation checkpoint — October 17, 2026

Core real-data implementation is now present across all seven pages. See the CURRENT section of docs/HANDOFF.md and docs/verification.md for actual completed modules and measured tests. Source and production build work; 31 backend tests pass. Real isolated saved-workflow execution, bounded recording reconstruction, scheduled approval/verification, discovery, global recording shortcuts, browser save/reload and persisted appearance were tested.

Do not interpret unchecked broad acceptance items above as claims that no code exists; they combine implementation with multiple scenarios, some of which have not all been exercised. Do not blindly mark the entire plan complete. Native capture-management switches are unsupported and omitted, browser notifications use an open-app fallback, shortcut mappings are fixed, evidence/provenance is limited to what the installed MCP supplies, repeat grouping is model-assisted, and live desktop tests cover Notepad only. No demo data or inactive placeholder controls were added.
