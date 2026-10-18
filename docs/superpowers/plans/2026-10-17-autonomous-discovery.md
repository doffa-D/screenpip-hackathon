# Autonomous Workflow Discovery Implementation Plan

> **For agentic workers:** Execute inline in this session, task by task; no delegation is requested.

**Goal:** Discover repeated original activities periodically and offer evidence-backed reusable drafts without executing them.
**Architecture:** A lifespan-owned worker uses the existing bounded Agent/MCP investigation and atomic JSON repository. Persist occurrences, semantic patterns, scan cursor/status and drafts together. Existing manual discovery remains compatible.
**Tech Stack:** FastAPI, asyncio, Pydantic, existing Azure/OpenAI Agent and Screenpipe MCP, React/TypeScript.
**Spec:** C:/Users/Doffa/.codex/attachments/b423c08d-443b-4e5b-8e3f-cb372f82916e/Pasted text.txt

## Global Constraints
- Original application evidence only; repeated frames/discussions do not establish repetitions.
- Dynamic read-only MCP tools; force time bounds. No new database or queue.
- Single process, atomic JSON persistence. Closing the desktop app stops scanning.
- Never execute discovered workflows; save and execution approvals remain explicit.
- Counts are distinct observed occurrences, never estimates extrapolated from frame counts.

### Task 1: Persistent discovery worker and API
Files: backend/autonomous_discovery.py, backend/config.py, backend/main.py, backend/agent.py, backend/chat.py.
- [x] Add validated occurrence/pattern/draft outputs. Reject unanchored sources, discussion provenance, out-of-range times; deduplicate by source IDs, timestamps and overlapping activity spans.
- [x] Use semantic goal/action comparisons against persistent candidates (including singleton candidates); unrelated goals remain separate. Confidence is model-assessed and conservatively limited by support.
- [x] Add interval/startup/lookback/chunk/overlap settings, one worker/scan lock, persistent cursor, recoverable interrupted/error status. Only advance successful chunks; disclose partial coverage.
- [x] Add list/detail/run/status/accept/dismiss/draft/save APIs; draft comparison reuses exact evidence without fetching unrelated history. Atomic commit before reporting success.
- [x] Unit tests use isolated repositories and fake investigations to exercise grouping, distinct goals, original source rejection, duplicates, incremental updates, confidence, dismissal, drafts, restart and retry.

### Task 2: Real Workflows UI
Files: frontend/src/Discovery.tsx, frontend/src/memory-pages.tsx, frontend/src/desktop-polish.css.
- [x] Show suggested/possible patterns with count, time range, last seen, apps, assessed confidence, explanation; frequency/recent/confidence sorting.
- [x] Show worker state, manual scan, real empty/error/coverage states; poll only while mounted.
- [x] Review exact occurrences/evidence; accept, dismiss, compare draft, edit title and explicit save to existing library. No automatic task selection or execution.
- [x] Build TypeScript/Vite and inspect actual page if browser available.

### Task 3: Validation and handoff
Files: tests/test_autonomous_discovery.py, scripts/test_discovery_live.py, .env.example, README.md, docs/HANDOFF.md.
- [x] Run full existing suite and production frontend build.
- [x] Run an isolated real MCP scan, record elapsed time, actual results and coverage without seeding fabricated patterns or changing user decisions.
- [x] Document configuration, thresholds, process lifetime and evidence/semantic uncertainty. Update handoff with actual validation results.

Validation: 53 tests passed; frontend production build passed. Real isolated scan39.934s/12 MCP reads/0eligible patterns, partial coverage explicitly reported. Desktop and mobile empty-state UI checked; no populated real-world grouping/draft success claimed.
