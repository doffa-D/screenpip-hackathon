# Seeded Suggestions, Real Execution Implementation Plan

> **For agentic workers:** Execute inline in this session; preserve the existing supervised execution gates.

**Goal:** Seed only discovery inputs, then review and approve the same durable workflow, execute through Zavora, and retain an event-backed report and user verdict.

**Architecture:** Extend WorkflowStore with revision-bound definition approval. Keep ExecutionManager as the sole desktop executor and generate deterministic reports from its events and input snapshot. Store user feedback with the run. Use existing review and Runs pages.

**Tech Stack:** Python, FastAPI, Pydantic, atomic JSON, React/TypeScript, Azure, Zavora MCP.

**Spec:** User attachment e21e5b3d-4dca-4c42-84fd-be8158cf1493/Pasted text.txt.

## Global Constraints
- Only discovery and historical source may be seeded; no new simulated executions.
- Same workflow ID/revision throughout review, approval, execution and report.
- Definition approval never authorizes desktop actions; every mutation retains its existing single-use approval.
- No coordinates, safety bypass, second executor, or app redesign.
- Live validation uses a unique disposable Notepad document; Gmail sending requires review of actual proposed actions.

### Task 1: Workflow definition approval
Files: backend/workflow_store.py, backend/main.py, backend/scheduler.py, tests/test_demo_pipeline.py.
- [x] Add durable reviewed revision and timestamp; edits invalidate review.
- [x] Add POST /workflows/{id}/approve with expected_revision; reject stale approval and incomplete inputs.
- [x] Require seeded workflows to be approved with exact saved defaults before manual or scheduled execution.
- [x] Test stale edits, persistence, exact values and scheduler gates.

### Task 2: Reports and result validation
Files: backend/models.py, backend/run_reports.py, backend/execution.py, backend/main.py, tests/test_demo_pipeline.py.
- [x] Capture workflow and effective values at execution start; correlate desktop attempts/results/errors with tool-call IDs.
- [x] Persist final typed report from actual events, including verification attempts and limitations. Successful tool return is applied, not independently verified completion.
- [x] Add GET /runs/{id}/report and POST /runs/{id}/feedback; reject active and simulated runs. Persist verdict, note and timestamp atomically.
- [x] Test success, failure, decline, interruption, feedback round-trip and simulated-run rejection.

### Task 3: Existing UI and seed integration
Files: frontend/src/{App.tsx,memory-pages.tsx,run-pages.tsx,types.ts}, scripts/seed_demo_data.py, tests/test_demo_seed.py.
- [x] Save/review values, approve exact saved revision, then execute same ID. Unsaved changes disable execution until saved and approved.
- [x] Show actual report and user verdict controls in Runs; preserve raw events and per-action approvals.
- [x] Seed memories/workflows/suggestions and disabled schedules only; remove creation of simulated run history. Keep old simulated history explicitly labeled.
- [x] Run backend suite and frontend build.

### Task 4: Real validation and handoff
Files: scripts/live_seeded_pipeline_test.py, docs/DEMO_DATA.md, docs/HANDOFF.md.
- [x] Run isolated real Azure/Zavora test with seeded saved workflow, revision approval, fixture-only action approval, fresh MCP verification, report and stored verdict.
- [x] Record timing and evidence, including failures; do not claim Gmail or report editing was live tested.
- [x] Document restart requirement, supervised limits, seed maintenance and final endpoints.
