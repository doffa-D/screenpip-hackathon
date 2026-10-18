# Sheets Execution Recovery Implementation Plan

**Goal:** Prevent model-authored window title and search argument errors from blocking the Sheets workflow.
**Architecture:** Normalize model requests before approval using exact titles from successful observations. The worker still validates the live title, so actual tab/window changes remain rejected. Return structured, compact screen observations and actionable recovery instructions.
**Tech Stack:** Python, existing FastAPI execution manager and Zavora worker, pytest.
**Spec:** The failed B26 run afe0fab8-f4b4-4851-b0c3-26f8dfe312f1 and the user request to fix it.

- [x] Add regression tests for model title omissions, real tab changes, native search argument mistakes, and large screen trees.
- [x] Add deterministic request normalization before validation/approval, successful-observation title tracking, and recovery guidance.
- [x] Replace cut-off inspection JSON with compact valid element observations when the tree is large.
- [x] Run focused execution/worker safety tests and a read-only live desktop check. Do not retry spreadsheet mutations as part of this check.


## Verification
- 145 focused tests passed: execution, execution recovery, Zavora client and Night Shift safety.
- Added a full execution-manager regression with shortened model titles, invalid native query arguments, approval payload inspection, and final formula verification (mock desktop/model).
- Live read-only Zavora: listed Chrome, repaired the supplied shortened title from the observed window, inspected depth 15, and received valid compact JSON (19,233 characters). No cells were changed and no full Azure Sheets execution was rerun.
- The standalone read-only probe produced a Windows asyncio pipe cleanup warning on process exit after successful results; no inspection call failed.
- Restart the desktop app/backend to load the updated execution prompt and request normalization; do not restart during an active workflow.
