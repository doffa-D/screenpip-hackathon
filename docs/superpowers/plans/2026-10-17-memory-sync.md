# Real memory indexing Implementation Plan

> **For agentic workers:** Execute incrementally in this session; preserve the existing single-process application.

**Goal:** Populate Home and Memories automatically from verified original Screenpipe task occurrences, with durable incremental sync and real runtime status across the existing app.

**Architecture:** Reuse DiscoveryService's semantic agent, provenance validation, deduplication, patterns and comparison drafts. A single sync coordinator runs that service and projects its verified singleton/repeated occurrences into a durable memory index; it does not create a competing scanner. Existing recording, scheduling, workflows and execution remain the authoritative stores.

**Tech Stack:** Python/FastAPI/Pydantic, atomic JSON, React/TypeScript.

**Spec:** C:/Users/Doffa/.codex/attachments/1bafd9be-2232-469b-970b-7b1eaf915098/Pasted text.txt

## Global Constraints
- Real data only; no fabricated completion, tasks, confidence, repetitions, schedules or runs.
- Preserve explicit selection, draft review/save, desktop approval, Stop and verification.
- Recording bookmarks existing history; never controls capture.
- Preserve Melon branding, compact reference styling and compatible endpoints.
- Downloads backup is not imported by this change; no replacement of Screenpipe history.
- One backend process per data directory; no new database.

### Task 1: Persistent memories and sync
Files: backend/memory_index.py, backend/memory_sync.py, backend/main.py, backend/config.py, backend/autonomous_discovery.py, tests/test_memory_sync.py.
- [x] Build a typed occurrence index retaining exact source evidence and its private reconstruction ledger, stable IDs, confidence/tags, first-created and last-updated timestamps. Deduplicate by original frames/overlap, preserving separate occurrences.
- [x] Add a single startup/periodic coordinator around existing discovery; durable sync state, successful cursor, bounded recent initial scan, error/interruption retry, nonblocking manual sync and shutdown. Project singleton and repeated occurrences; patterns remain semantic and user decisions persist.
- [x] Add GET /sync/status, POST /sync/run, GET /memories with local query/date/app/source filters, GET /memories/{id}. Durable memories resolve through existing task reconstruction and explicit saving.
- [x] Merge validated dynamic task searches into the index without trusting invented app metadata. Preserve unindexable search results in the existing task cache.
- [x] Recover derived projections from canonical occurrence records. Preserve damaged JSON as timestamped quarantine files and expose recovery warnings rather than discard history silently.
Validation: fixture-driven initial, repeat, incremental, duplicate, distinct occurrences, singleton, semantic grouping, decision persistence, restart and corrupted-file tests; existing suites.

### Task 2: UI uses indexed data
Files: frontend/src/App.tsx, memory-pages.tsx, MemorySync.tsx, support-pages.tsx, types.ts, reference-theme.css.
- [x] Load durable memories on boot and refresh after sync; Home recent cards newest-first with loading/empty/error states.
- [x] Memories defaults to local data; local text/date/app/source filtering, optional deeper dynamic MCP search, explicit evidence selection and reconstruction links.
- [x] Shared plain-language sync indicator and manual action on Home/Memories/Settings. Settings shows actual cursor, counts, error, provider checks and schedule/recording state.
- [x] Audit Record/Schedule/Runs existing real bindings and supply explicit first-load/error/empty states; open a newly reconstructed recording for review without saving/executing it.
Validation: production TypeScript build, isolated browser QA desktop/mobile, API-backed real history smoke test.

### Task 3: Regression, live verification and documentation
Files: tests/test_memory_sync.py, tests/conftest.py, scripts/test_memory_sync_live.py, README.md, docs/HANDOFF.md.
- [x] Run all existing search, recording, markers, schedule recurrence/dispatch, approval/Stop/verification and persistence tests.
- [x] Run timed real Screenpipe/Azure scan in isolated storage; report actual memory/pattern counts and coverage without inventing populated results.
- [x] Verify UI reads real indexed objects through an isolated backend, filter/review navigation, no horizontal overflow, then stop preview.
- [x] Document environment settings, API behavior, startup/restart, partial coverage and app-open scheduling constraints.

## Verification
73 backend tests passed (1.29 s); production build passed. Final real 24-hour sampled scan: 65.288 s, 14 MCP reads, one source-backed Notepad edit, zero repeated patterns, zero saved/executed workflows. Populated Home/Memories/evidence links checked through an isolated backend; seven feature routes passed desktop/mobile overflow checks. Pattern draft/save and scheduled approval/Stop flows are fixture regression tests, not new live desktop actions. Native 8765 was left running; reopen Melon to load the upgrade.
