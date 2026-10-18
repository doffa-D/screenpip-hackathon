# Sheets Demo Executor Implementation Plan

**Goal:** Remove model-driven repetition from an explicitly selected, single-cell Sheets SUM workflow.
**Architecture:** Opt-in execution_mode=sheets_sum_v1 routes the existing ExecutionManager to a bounded deterministic executor. Other workflows retain the agent. Use existing approvals, live window identity checks, event reports and cancellation. Never auto-fallback to agent after a partial edit.
**Tech Stack:** Python, FastAPI, Zavora MCP.
**Spec:** Current user request for a simple reliable Sheets demo: G10 =SUM(G3:G9).

- [x] Add backend/sheets_executor.py: validate a docs.google.com spreadsheet URL, gid, SUM range and matching adjacent destination. Open once, identify Chrome and confirm exact live URL, activate, select target and verify once, type once, reselect and verify, check save with bounded polling. No source audit, Undo, screen-reader setup or numeric invention. Log each native action/check with correlation IDs.
- [x] Integrate explicit mode before model client creation in backend/execution.py; preserve finally/report handling and errors. Scoped unattended runs are rejected for this manual-demo-only mode.
- [x] Tests in tests/test_sheets_executor.py: full normal path, approval before mutation, wrong URL/target rejection, no formula input on selection failure, no Undo/retyping on verification failure, permission cancellation, no model request in opt-in route.
- [x] Test the real workflow in an isolated execution manager using actual Zavora, confirm formula/save and record timing. Stop on unexpected state. No API/state-file overwrite of the live process.
- [x] Update saved workflow defaults through revision API and document restart requirement for current desktop process.

## Validation
- 49 targeted tests passed before live verification.
- Real isolated ExecutionManager + Zavora test: completed in 10.146 seconds, 17 desktop tool calls including bounded save-status polling, zero model calls. G10 formula and Saved to Drive verified. Numeric total was not independently read.
- Evidence: artifacts/sheets-total-row/fixed-live/run.json. This test uses isolated run persistence and does not appear in the running app history.
- Existing Windows async subprocess cleanup warning occurred after successful completion. It did not invalidate the live checks.
- Saved workflow revision 23 includes execution_mode=sheets_sum_v1. Running desktop backend must restart to load new route; workflow must be approved at its current revision before UI execution.

Broader regression checks: 157 passed in 3.94 seconds (Sheets, execution, recovery, Zavora, Night Shift).
