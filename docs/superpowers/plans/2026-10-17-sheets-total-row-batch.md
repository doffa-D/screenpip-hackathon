# Sheets Total Row Batch Implementation Plan

**Goal:** Populate B10:G10 quickly from B3:G9 with six SUM formulas, without model calls.
**Architecture:** Extend the existing controlled executor with sheets_totals_v1, validate a bounded adjacent total row, paste one TSV row, verify each formula from its selected address and formula bar, and verify saving. Keep single-cell mode compatible, approvals and permission/window checks intact. No clearing source data or guessing totals.
**Tech Stack:** Python, Zavora MCP, Google Sheets.

- [x] Add total-row specification and batch payload to backend/sheets_executor.py; keep sheets_sum_v1 unchanged.
- [x] Route explicit totals mode in backend/execution.py.
- [x] Tests: validate bounds/column alignment; prove one batch write, all six formula checks, failed cell stops without repaste, approvals preserved, no model requests.
- [x] Real test via isolated ExecutionManager, exact sheet and B10:G10 only, record duration and verified formulas/save.
- [x] Update live saved workflow through API, record restart requirement and honest verification limits.

## Live result
Actual isolated ExecutionManager + Zavora execution completed in 11.410 seconds with 34 bounded tool calls, zero model calls. A single TSV paste filled B10:G10; each of the six SUM formulas was reselected and independently verified, followed by Saved to Drive. Numeric totals were not independently read. No source clearing was performed. Evidence: artifacts/sheets-total-row/batch-live/run.json. This isolated test is not in the running app history.

Saved workflow revision 25, Google Sheets - Calculate all totals (B10:G10), explicitly selects sheets_totals_v1. Restart the existing Melon process to load the updated mode, then approve the edited workflow in the UI. No frontend rebuild required.
