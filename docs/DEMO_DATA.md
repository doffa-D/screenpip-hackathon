# Seeded discovery, real supervised execution — current strategy

Only the discovery source and repeat counts are simulated. Suggestions link to the existing saved workflow IDs and review page. No frontend fixture arrays or alternate desktop executor are used.

Current offline seed creates three memories, three saved workflows, three suggestion records and two disabled schedules. It creates **zero run records**. Reseeding removes only legacy records marked both origin=demo and source_kind=seeded_demo from the run store; actual executions of seeded workflows are real execution records and remain intact. Existing edited workflows are preserved.

Close Melon and other backends before running `.venv/Scripts/python.exe -m scripts.seed_demo_data`. Reopen Melon after updating code; reloading cannot replace the running backend. No maintenance writes were made to the running user's data during this update.

## Product flow

1. Workflows → Demo suggestions → Review demo workflow.
2. Open the intended application/window yourself. Edit values and target instructions.
3. Click **Approve workflow & values**. This saves the same workflow and records its approved revision and timestamp. Missing inputs or stale revisions are rejected. Edits invalidate approval.
4. Click **Start desktop run**. The saved ID, approved revision, full workflow snapshot and effective values are attached to the real run.
5. In Runs, approve or decline each proposed desktop action. Definition approval does not authorize arbitrary clicks or messages. Stop remains available.
6. The existing Azure agent inspects the current desktop through Zavora, proposes actions and verifies results. No historical coordinates or synthetic results are supplied.
7. Runs shows the final report and two result-review actions. Verdict, notes and timestamp are stored with the run. Feedback does not automatically train the agent.

The raw API likewise requires seeded execution to match the approved saved defaults. Editing defaults requires saving and approving again. Scheduled seeded workflows use the same check on their pinned snapshot; old unapproved schedule snapshots must be recreated after approval. Scheduled desktop actions still pause for per-action approval.

## New endpoints

- POST /workflows/{id}/approve — `{ "expected_revision": 2 }`.
- GET /runs/{id}/report — available after termination; rejects simulated history.
- POST /runs/{id}/feedback — `{ "verdict": "looks_good" | "something_wrong", "notes": "..." }`; rejects active/simulated runs.

Reports are built from events, not invented by a model: workflow name/revision, start/end, status, effective inputs, instructions, attempted mutations, successful desktop-tool returns, live verification checks and errors. A successful tool return is not an independently verified business outcome. There are no screenshots or automatic skipped-step classification. Legacy runs disclose absent input/action correlation metadata.

## Validation — 2026-10-17

Real run: artifacts/seeded-real-execution/57a8fa42a9ad. Seeded Notepad workflow demo:workflow:notepad, approved revision 2, run e4542cfd-fddd-4e27-9b08-30360640008e. Actual Azure reasoning + Zavora inspection + one narrowly approved editor mutation + exact verification completed. Execution request to final report: **17.761 seconds**; total including independent fresh MCP verification and stored feedback: **21.708 seconds**. Test fixture changed hello word → hello world, with no Save operation.

The test harness approved only an exact set_value=hello world in its unique fixture window. It recorded feedback explicitly marked as test-harness feedback, not a human verdict. Run report and verdict survived a new ExecutionManager reading the store.

Repeat with `.venv/Scripts/python.exe -m scripts.live_seeded_pipeline_test`. It uses an isolated store and a new Notepad file. It does not send Gmail messages, modify the user's workflow store, or bypass product approvals. The temporary unsaved Notepad document is left open for inspection.

Browser QA used a copy of that store on an isolated preview: approved values survived reload; editing disabled Run; Approve persisted the same workflow revision and re-enabled Run; the report displayed one actual action and live check; Something went wrong stored and displayed feedback. No desktop execution was launched from browser QA. No page errors or horizontal overflow after configuring the preview's explicit local origin. Main app origin protection remains unchanged. Gmail sending and Google Docs editing have **not** been live demonstrated and may still be blocked by unsupported/ambiguous accessibility controls.

## Earlier seed history (superseded where noted)

# Demo data validation — 2026-10-17

## Files changed

Backend: `backend/models.py`, `backend/memory_index.py`, `backend/workflow_store.py`, `backend/scheduler.py`, `backend/main.py`.
Frontend: `frontend/src/types.ts`, `frontend/src/components.tsx`, `frontend/src/Memories.tsx`, `frontend/src/memory-pages.tsx`, `frontend/src/run-pages.tsx`, `frontend/src/support-pages.tsx`; new `frontend/src/DemoSuggestions.tsx`. Production `frontend/dist` rebuilt.
Scripts/tests: new `scripts/seed_demo_data.py`, `scripts/clear_demo_data.py`, `tests/test_demo_seed.py`.
Documentation: `README.md`, `docs/HANDOFF.md`, `docs/superpowers/plans/2026-10-17-demo-seed.md`, this report. Private validation artifacts: `artifacts/demo-seed-before.json`, `artifacts/demo-seed-validation.json`.

## Data seeded

Three stable demo memories and saved workflows: Send project reminder email (today 10:05 Europe/Paris), Edit Notepad text (today 09:40), Create weekly project report (yesterday 16:30). Gmail recipient mzbakasta@gmail.com, subject Reminder: Project Update, exact multiline body ending Houssam. Notepad replaces hello word with hello world without claiming a save. Report uses the exact requested title/progress/next-steps values. All evidence says seeded_demo, with no frame IDs or Screenpipe ledger.

Two disabled schedules: daily email at19:00, weekly report Monday09:00, Europe/Paris. Three synthetic historical runs: Notepad/report completed, Gmail cancelled. These explicitly say never executed and contain no successful verification event. Three separate demo suggestion records contain synthetic counts12/5/4; real discovery patterns/statistics are untouched.

## Observed verification

- Seed command twice:3 memories,3 workflows,2 schedules,3 runs,3 separate demo patterns; no duplicates.
- Cleanup command removed exactly these counts. Existing original workflow/run and other tracked stores matched pre-seed values exactly. Reseed produced the same counts.
- Native Melon restarted with project .venv runtime. Initial system-Python launch lacked webview; corrected to .venv/Scripts/pythonw.exe. If an old startup-error dialog is still visible, dismiss it; the correctly configured app is running.
- HTTP200: GET /memories3demo; /workflows3demo; /schedules2demo(all disabled); /runs3demo plus1 existing real run; /demo/patterns3demo. Archived original workflow retained on disk, excluded normally from active library.
- POST /tasks/demo:memory:gmail/reconstruct200: exact recipient/subject/body and demo-only evidence; no model/MCP lookup.
- Browser opened Home, Memories, Workflows, Schedule, Runs. Seeded content and Demo labels displayed on each, no page alerts or horizontal overflow. Opened Gmail saved workflow review and checked actual editable values. Corrected all demo review/evidence copy to avoid claiming original recorded activity. No Start run, approval, or schedule-enable action clicked.
-76 backend tests passed1.36s; production TypeScript/Vite build passed (index-L55qdg_1.js).

## Operation

Close Melon AND any web backend before maintenance, then from project root with .venv activated:

```powershell
python -m scripts.seed_demo_data
python -m scripts.clear_demo_data
```

Both commands accept --data-dir. They refuse writes while supported native8765/development8000 servers are listening, preventing stale in-memory overwrites. Custom-port servers must also be stopped manually. Stores use existing atomic Repository.write (per file, not a multi-file transaction). Stable demo IDs are collision checked before writes; reseeding preserves edited existing demo objects. Cleanup requires explicit origin=demo AND source_kind=seeded_demo; normal real execution records are preserved even when a demo workflow supplied their inputs. Startup caches reload after reopening the app.

Demonstration content is left seeded. No demo task was discovered by Screenpipe or executed. Email sending and all other desktop mutations retain existing explicit approval and verification.
