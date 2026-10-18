# Google Sheets total row Implementation Plan

> Execute inline in this session. No subagents or unrelated spreadsheet edits.

**Goal:** Update the existing saved workflow to calculate B26:G26 from rows 19:25 and verify live results.
**Architecture:** Use the running FastAPI revision API, retaining original history. Test the saved definition with the real Azure/Zavora executor. Improve instructions from observed live accessibility evidence, without weakening approvals or window identity.
**Tech Stack:** Python, FastAPI, Azure, Zavora MCP, Google Sheets in Chrome.
**Spec:** User request: sum seven category rows across all six total columns, preserving the rest of the sheet.

## Global Constraints
- Only B26:G26 may be changed. Preserve source data, existing formulas elsewhere, and formatting.
- Formulas must use live source values. Example totals are not hard-coded.
- Expected pasted-data sums: 8, 386946, 358071, 382466, 111272, 1545465. The supplied example disagrees for E, F and G.
- No overlapping desktop runs. No false claims of verification.

### Task 1: Save complete workflow
**Files:** live workflow cc962ae9-e8fe-4bc5-a493-11466945de84; backup artifacts/workflow-updates.
- [ ] Inspect current revision and active execution.
- [ ] PATCH title, definition, and run defaults with formulas =SUM(B19:B25) through =SUM(G19:G25), preserving provenance.
- [ ] Read back saved revision and validate every column/reference.

### Task 2: Real execution and verification
**Files:** artifacts/sheets-total-row; backend/execution.py only if live evidence proves a reusable prompt issue.
- [ ] Discover current UI controls with Zavora after earlier run finishes.
- [ ] Establish live selected cell and numeric reading route, including screen-reader support if required.
- [ ] Approve and execute the saved exact workflow through FastAPI with supervised scoped action review.
- [ ] Capture final report and independent live verification of formulas, results and Saved to Drive.
- [ ] Document actual outcome and remaining limitations. Run affected tests only if code changes.
