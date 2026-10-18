# Melon — memory to action

Python 3.12+ FastAPI backend with your own Azure/OpenAI tool-calling agent.
It launches `npx -y screenpipe-mcp@latest` over stdio and discovers real tools
on every request. A React frontend lets you select a past task, review its workflow,
and repeat it through a custom Azure/OpenAI agent using Zavora computer-use MCP. No Pi or UI-TARS.

## Run (PowerShell)

Install Node.js 20+/npm and run the Screenpipe recorder locally first. From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
# Only on first setup; preserve an existing configured .env:
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env with your Azure endpoint, API key and deployment name.
npm --prefix frontend ci
npm --prefix frontend run build
.\run.ps1
```

`requirements.lock.txt` also records the exact tested Windows/Python 3.12
environment; use `pip install -r requirements.lock.txt` for that environment.

Use an Azure deployment supporting Chat Completions, function tools and JSON
object output. For OpenAI set `AI_PROVIDER=openai` and `OPENAI_API_KEY`;
`OPENAI_MODEL` selects the model. Configure `AGENT_TIMEZONE` for local calendar
questions. The backend supplies a fresh timezone-aware clock each request.
For this workspace's Azure `gpt-6-luna` deployment, `.env` sets
`REASONING_EFFORT=none`: that deployment requires it for Chat Completions tool
calls. Leave it unset for models that do not support this parameter.
Screenpipe connection variables in `.env` are forwarded to the child process;
existing process environment variables take precedence. The MCP server can also
discover recorder authentication from its local installation.

App: http://127.0.0.1:8000

Swagger: http://127.0.0.1:8000/docs

After setup, `.\run.ps1` starts the whole app. Use one server worker.
For frontend development, run the backend on port 8000 and `npm --prefix frontend run dev`
in another terminal; open http://127.0.0.1:5173. Node 24 is the tested runtime.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$found = Invoke-RestMethod http://127.0.0.1:8000/tasks/search -Method Post -ContentType application/json -Body '{"message":"Find all emails I sent today"}'
$found | ConvertTo-Json -Depth 10
# Inspect the returned list and deliberately choose an id yourself:
$chosenId = Read-Host 'Task id to reconstruct'
Invoke-RestMethod "http://127.0.0.1:8000/tasks/$chosenId/reconstruct" -Method Post | ConvertTo-Json -Depth 15
```

Search returns a JSON array of `{id,title,timestamp,summary,evidence}`. Similar
occurrences remain separate. Evidence contains `call_id`, an exact `quote` from
the retrieved MCP response, and `source_kind`. Backend-generated task IDs select
the exact occurrence; nothing automatically selects or reconstructs it.

Reconstruction returns `{goal,historical_values,steps,missing_values,evidence}`.
Historical values are `{value,evidence}` entries. Steps contain `description`
and `evidence`. Missing or masked values are listed explicitly; steps describe
observed history without mouse coordinates. These are historical instructions,
not executable UI-TARS commands.

## How it works

### Repeat a selected task

1. Search in the app and choose a specific occurrence. Nothing is auto-selected.
2. Review the reconstructed steps and source references. Edit recovered values if needed.
3. Supply missing information. For an unknowable historical detail, explain what the new run should do rather than making it up.
4. Open the target app yourself and identify the document/window in the execution instructions.
5. Start the run. The agent lists apps, inspects current accessibility trees, and proposes one action at a time.
6. Review the exact window ID/title, element role/label, action and text, then approve or decline. Declining stops the run.
7. Watch live events. The agent reads the UI again to verify results. Stop ends further actions; it does not undo completed changes.

The execution agent dynamically chooses tools backed by Zavora MCP; it does not convert history into a fixed macro. It has no shell or app-launch tool. Controls that are absent from the accessibility tree or do not support the requested action can block a run. This is a local hackathon app, not unattended arbitrary desktop automation. Semantic success still depends on the model choosing the right expected result; the backend additionally requires a successful exact-text verification after the final mutation.

### API additions

| Endpoint | Purpose |
|---|---|
| `GET /tasks` | Saved unexpired occurrences |
| `GET /tasks/{id}/workflow` | Saved reconstruction |
| `POST /tasks/{id}/execute` | Start a reviewed task; returns a run with HTTP 202 |
| `GET /runs` | Saved run summaries |
| `GET /runs/{id}` | Current status, pending action, events and elapsed time |
| `POST /runs/{id}/approval` | Approve/decline one exact action ID |
| `POST /runs/{id}/stop` | Cancel pending work and stop the active native call |
| `GET /desktop/apps` | Read current accessible apps |

Execution body: `{"values":{},"missing_values":{},"instructions":"Use my new Notepad test document"}`. `values` contains replacement historical fields; unchanged values remain in the reconstruction. `missing_values` maps each exact missing-value description to the user's answer. Approval body: `{"action_id":"pending-action-id","approve":true}`. Duplicate/stale approvals fail with 409. Only one desktop run can be active. Default limits: 24 model rounds, 600 seconds including approval wait, 20 seconds per native tool call. Configure these in `.env.example`.

The browser polls the run once per second; it never receives model credentials. The server rejects foreign browser origins on writes and unexpected Host headers. Bind to `127.0.0.1`; do not expose it publicly without adding authentication and access controls.

### Night shift (proactive, approved-scope autonomy)

Screenpipe history already feeds workflow discovery. Night shift reads those verified records and notices what you
usually do next, so Melon can prepare the step you forgot while you are away.

1. **Notice.** `backend/routine.py` mines "after A you usually do B" from real timestamps (support, probability, and a
   base-rate lift so an all-day task is not mistaken for a routine). The latest A that never got its B becomes a proposal.
   An optional model pass (`NIGHTSHIFT_UNFINISHED_PASS`) flags work left open, e.g. a draft never sent; its findings are
   validated against real occurrence and workflow ids and are dropped otherwise.
2. **Approve a scope.** Melon only does steps you saved as a workflow, reviewed and approved (exact values). For each
   proposal you approve ONE night: allowed websites and apps, an action budget, and prepare-only by default (no Send,
   Submit, Delete, Pay unless you tick the box). Approval expires when the night window ends.
3. **Do it overnight.** Inside the window (default 23:00–06:00, `Settings` on the Night shift page) the approved workflow
   runs through the normal executor, including live verification. `backend/scope.py` decides every change without a model;
   anything outside the scope, any final-step control, any control it cannot classify stops the run instead of guessing.
   Before starting, Melon re-checks that you did not already do the step yourself, that the workflow was not edited and
   that the desktop is unlocked.
4. **Morning report.** `GET /nightshift/report` and the Home card summarise what was noticed, what was done (actions,
   live checks), what stopped and why. You mark each result "Everything looks good" or "Something went wrong"; the verdict is
   stored on the run and a "wrong" verdict suppresses that suggestion for 14 days.

Limits to know: it runs only while Melon is open and the PC is on, signed in and unlocked (the screen may be off); the final-step
guard is label-based and best effort, so keep "prepare only" for anything you cannot undo; Melon repeats the saved workflow's values and
does not carry data from the missed step into the follow-up.

| Endpoint | Purpose |
|---|---|
| `GET /nightshift/status` · `PATCH /nightshift/settings` | Window, limits, on/off |
| `POST /nightshift/analyze` · `GET /nightshift/proposals` | Look for gaps now · list proposals |
| `POST /nightshift/proposals/{id}/approve` · `revoke` · `dismiss` | Approve one night's scope · take back · not useful |
| `POST /nightshift/proposals/{id}/run-now` | Rehearse an approved proposal now (45 min, same scope) |
| `POST /nightshift/proposals/{id}/review` · `GET /nightshift/report` | Validate the result · morning report |
| `POST /nightshift/demo` · `DELETE /nightshift/demo` | Reset / remove the fake demo examples. They load automatically at startup while no real proposals exist (`NIGHTSHIFT_DEMO=false` turns that off); demo items can never run |

### Full live execution test

```powershell
.\.venv\Scripts\python -m scripts.live_execute_test
```

This test requires the existing real `artifacts/notepad-occurrences/session.json` and `workflow.json` from the explicitly selected 20:03 occurrence. It creates a NEW Notepad fixture, uses real Azure reasoning and Zavora MCP through the API, and automatically approves only `set_value("hello world")` scoped to that exact test window. Any other proposed change is declined. It saves the full run under `artifacts/full-app-live/` and reads the final text through a separate MCP session. No email sending or external submissions are tested.

- `config.py`: environment configuration.
- `mcp_client.py`: subprocess lifecycle, initialization, paginated tool discovery,
  schema access, tool calls, timeouts and cleanup. Each request owns its session;
  no background MCP task or cross-task context-manager teardown.
- `screenpipe_tools.py`: reviewed read-only tool names and dynamically discovered
  schemas. New/mutating tools fail closed. No fixed search keyword or fixed tool
  sequence. Text-only output keeps screenshots out of the model context.
- `agent.py`: bounded iterative reasoning, tool errors returned to the model,
  search refinement/context retrieval, JSON validation and exact-quote checking.
- `models.py`: Pydantic request, occurrence and reconstruction contracts.
- `main.py`: routes, local-only request checks, saved tasks and frontend hosting.
- `execution.py`: live execution agent, approval state machine, cancellation and logs.
- `desktop.py` / `desktop_worker.py`: validated Zavora adapters and isolated MCP worker calls.
- `repository.py`: atomic JSON storage; no database service.
- `frontend/`: React + TypeScript interface, responsive layouts, live run polling.

The agent chooses tools and filters. It is instructed to inspect original
application activity, distinguish sent emails from drafts, group captures by
occurrence, honor requested time bounds, and retrieve neighbors/full frames when
necessary. Summaries and ChatGPT discussions alone cannot ground a returned task.
Exact-quote validation checks provenance; semantic relevance, source classification,
completeness and occurrence grouping still depend on the model and recorder data.
It is not a guarantee of exhaustive search. Truncated results are marked for the
agent to page/narrow. Budget exhaustion is an error rather than fabricated output.

Use one server worker. Tasks expire after one hour by default, are capped at 200,
and persist across restarts until expiry. Unknown or expired selections return 404.
Tasks, evidence and reconstructed workflows are saved in `.data/tasks.json`.
The latest 100 runs are saved in `.data/runs.json`; active runs become interrupted
on restart and never resume automatically. `.data/` is ignored by Git. These files
contain private history and desktop text; they are local plaintext, not encrypted.
`/health` reports process liveness; it does not imply model/recorder readiness.
Configuration errors return 503, dependency errors 502, request timeouts 504.
Two investigations can run concurrently; waiting time counts toward timeout.
Keep the server on localhost: authentication/multi-user isolation is outside this
hackathon milestone. Retrieved history is sent to the configured model provider.

## Verify

```powershell
.\.venv\Scripts\python -m scripts.probe_mcp
.\.venv\Scripts\python -m pytest -q
# With the server running:
.\.venv\Scripts\python -m scripts.smoke_search
```

The probe launches the actual npm stdio server, saves tool schemas (no history)
to `docs/mcp-tools.json`, and calls the discovered health tool. Tests use synthetic
history and a scripted model for repeatable multi-turn behavior. The smoke script
uses the actual HTTP server and configured model; it does not substitute a mock.
See `docs/verification.md` for results from this workspace.

For real recorder data, an activity summary, and three model-backed endpoint
requests (no mocks), run:

```powershell
.\.venv\Scripts\python -m scripts.live_test --interactive
```

Actual responses are saved under `artifacts/live-test/` (ignored by Git).
Interactive mode displays candidates and asks you to choose an id before testing
reconstruction. Without model credentials, the saved endpoint responses record
the configuration failure; they are not successful agent search results.
The harness also saves its real task/evidence session locally. An explicitly
selected id can be reconstructed in a later test process with:

```powershell
.\.venv\Scripts\python -m scripts.live_test --output-dir artifacts/notepad-occurrences --reconstruct-id edba6f9c-ca66-43ce-8181-ab5806842c50
```

This restores only the selected saved test occurrence into process memory;
production endpoints persist selected data locally with an expiry. Raw test history stays in the
ignored artifacts directory. Tool traces record tool names, outcome and text
sizes, so you can verify dynamic calls without printing entire captures.
## Zavora desktop execution

The app runs `npx -y @zavora-ai/computer-use-mcp@7.6.1` over local stdio,
with the accessibility (`ax`) profile. No xa11y package is needed for the app
or full API replay test. The first run downloads the npm package; it may take
longer than the normal desktop timeout. Warm the package with the diagnostic
command below before using the Run button.

```powershell
.\.venv\Scripts\python -m scripts.test_computer_use_mcp
.\.venv\Scripts\python -m scripts.live_execute_test
```

The execution agent sees `list_apps`, `inspect_app`, `act`, and `verify_text`.
These use actual MCP-discovered schemas underneath: `list_windows`, `get_ui_tree`,
`find_element`, `set_value`, `press_button`, and `click_element`. Unreviewed tools,
including scripts, raw keyboard input and clipboard access, are not exposed.
All mutations require approval, an inspected window, its exact current title,
and one unique exact role/label match. If a title changes, refresh the window list.
Verification is an exact value or label read from the window that was changed.
The desktop tools are checked on request; `/health` checks npx availability only.

Each desktop operation runs in an isolated Python/MCP worker. Stop and timeout
terminate its Windows process tree; already applied changes are not undone.
Use an interactive Windows desktop and leave the target window open. Remote
sessions, inaccessible controls and ambiguous labels can block execution.
Native actions can race with human interaction; inspect the proposed target
before approving and avoid switching the document during an approved change.

`backend/computer_use_mcp.py` is the reusable, schema-validating stdio client.
The pinned package needs no model credentials. Its diagnostic tool and native
server maintain a local audit log as reported by `doctor`. Reports under
`artifacts/computer-use-mcp/` may contain private desktop metadata.

Legacy standalone xa11y comparison scripts and their optional requirements file
are retained for reference; they are not used by the application.


## Melon workspace features (October 17, 2026)

The seven-page frontend now uses the supplied blue/lavender reference design. Home and Memories display real discoveries; Workflows has a durable saved library and evidence-backed repeat discovery; Record bookmarks intervals; Schedule manages persisted rules; Runs shows live approvals and verification; Settings checks real connections and applies preferences.

- Save a reconstructed memory with **Save workflow & values**. Reopen it from Workflows after search results expire. Rename/archive are persisted; edits use optimistic revision checks. Original historical facts stay separate from run defaults and previous revisions.
- **Start recording saves a server timestamp only.** Stop fixes the end timestamp and launches a background investigation of existing Screenpipe history. Melon never toggles Screenpipe recording. A health check runs after the bookmark is saved. Missing input events stay missing, even if the final text was captured. Failed processing can be retried against the same interval. Processing interrupted by restart is marked interrupted; active bookmarked intervals remain available to stop.
- Repeated-task discovery investigates the past seven days from the UI (the API accepts another bounded interval). Groups contain distinct individually inspectable occurrences and an observed count, with explicit coverage limits. Counts are not a guarantee of exhaustive capture.
- Schedules pin the saved workflow revision and its reviewed run defaults. They support once/daily/weekly/monthly, editing, pausing, history and deletion. The local server and an unlocked interactive Windows desktop must be available. Every mutation retains the approval gate. A busy desktop blocks the occurrence rather than running concurrently. Missed occurrences are recorded without catch-up. Archiving a workflow pauses dependent schedules.
- Recurrence uses IANA timezones. Monthly dates clamp to the last day; spring DST times that do not exist are skipped, and repeated autumn times use the first occurrence only. Keep one server process/worker; automatic reload can interrupt jobs and shortcut registration.
- Settings performs live Screenpipe/model/desktop tests with timing, shows actual free disk space, stores light/dark/system and accent preferences, and gates desktop execution. Disabling desktop control stops active work. Provider settings support a write-only replacement key; existing keys are never returned. Overrides are stored in ignored local `.data/provider.json` and take precedence over `.env`; protect that local directory like `.env`.
- Windows global shortcuts: Ctrl+Shift+R start/stop a segment; Ctrl+Shift+M marker; Ctrl+Shift+K search; Ctrl+Shift+Space open Melon; Ctrl+Shift+Enter opens the latest workflow review. Settings reports actual registration/conflicts. The last shortcut never executes or approves a change.
- Browser run notifications require an open app and browser permission. In-app notices remain available. This is not a background native notification service.
- Screenpipe capture settings remain managed in Screenpipe because no verified capture-setting write capability is exposed by this integration. No cosmetic capture toggles are provided.

Additional routes: GET/POST `/workflows`, GET/PATCH/DELETE `/workflows/{id}`, POST `/workflows/{id}/execute`; GET `/workflow-groups`, POST `/workflows/discover`; GET `/recordings`, POST `/recordings/start`, POST `/recordings/{id}/markers`, POST `/recordings/{id}/stop`, POST `/recordings/{id}/retry-processing`, GET `/jobs/{id}`; GET/POST `/schedules`, PATCH/DELETE `/schedules/{id}`, POST `/schedules/preview`, GET `/schedules/{id}/occurrences`; GET/PATCH `/settings`, PATCH `/settings/provider`, GET `/capabilities`, POST `/connections/{screenpipe|model|desktop}/test`, GET `/system/status`, GET `/shortcuts`.

Search additionally accepts optional `period` (`Today`, `Yesterday`, `This week`) and `source` (`Email`, `Documents`, `Browser`). Calendar filters resolve on the server in `AGENT_TIMEZONE`; bounded investigations only offer MCP tools whose current schemas support time bounds. Source categories guide the custom agent's evidence assessment rather than assuming one app name.

Run the expanded isolated real integration test:

```powershell
.\.venv\Scripts\python -m scripts.live_feature_test
```

It uses real Azure, Screenpipe and Zavora, the previously user-selected historical Notepad task, and uniquely named new test documents. It tests saved execution after clearing the temporary task cache, approval, independent verification, recording reconstruction, and a near-term scheduled run. Only the exact fixture's `hello world` replacement is approved; other proposed changes are declined. Temporary schedules are removed. Test documents stay open and unsaved. Private evidence and timings are saved under ignored `artifacts/real-features/live/`.

### Melon Desktop (Windows — primary launch)

Melon now opens in its own native Windows window using Edge WebView2. No browser tab or separately started backend is needed. The existing React interface, FastAPI agent, Screenpipe MCP and Zavora execution remain intact.

One-time setup, from this project folder:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-desktop.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
powershell -ExecutionPolicy Bypass -File scripts/install-desktop-shortcut.ps1
```

Keep Microsoft Edge WebView2 Runtime installed (normally present on Windows 11), Node/npx available for the MCP servers, Screenpipe running, and your existing `.env` configured. This is a source-installed desktop application: keep the project and `.venv` in place. It is not a standalone installer or a self-contained executable.

Double-click **Melon** on the desktop, or `Melon.vbs` in this folder. For visible startup diagnostics, run `./run.ps1` (or `./run-desktop.ps1`). Startup errors are written to `.data/desktop.log`; no credentials are embedded in the launcher. Desktop installation preserves this project's existing `.env` and `.data`.

The desktop process owns one backend on `127.0.0.1:8765`. A second instance refuses to start. It does not terminate any existing development server on port 8000. Avoid running both against the same data folder: they would both schedule work and compete for shortcuts. Stop your old web server before normal desktop use. Global navigation shortcuts restore the native Melon window.

Closing the window asks for confirmation, then closes the backend, stops active execution and unregisters shortcuts. Schedules run only while Melon is open; previously missed schedules are not replayed on reopen. There is no system tray/background service. Existing browser notifications may be unavailable in WebView2; in-app notices remain available. Native OS notifications are not added by this conversion.

For backend-only development use `./run-web.ps1`; API documentation for the desktop instance is at `http://127.0.0.1:8765/docs`.

Desktop smoke test (opens and closes a real native window):

```powershell
.venv/Scripts/python.exe desktop_app.py --smoke-test
.venv/Scripts/python.exe -m pytest -q
```

Smoke results are written to `artifacts/desktop-smoke.json` or `artifacts/desktop-smoke-error.txt`. The test renders real pages and reads actual local APIs; it does not execute a workflow or create demo data.

## Melon assistant
Choose **Chat** in the sidebar. Ask it to find tasks, list workflows, manage recording bookmarks and markers, inspect jobs, discover repeated work, manage schedules, check connections, change preferences, or stop runs. It uses the same real APIs as the screens. Searches and reads run directly; other actions appear as review cards with exact inputs and Confirm/Dismiss. Select a returned occurrence explicitly before reconstruction. Review execution inputs before confirming a run; approve desktop actions in Runs. Provider secrets stay in Settings.

Chat conversations live in memory, expire after two hours of inactivity and reset on app restart. Failed/expired conversations can be restarted by reopening the app. Chat does not run in the background after closing Melon. Responses show elapsed seconds; detailed real API results are expandable. Restart Melon after installing this update.

Developer checks: `.venv/Scripts/python.exe -m pytest -q`; `npm --prefix frontend run build`. Optional live Azure/OpenAI integration: set PYTHONPATH to the project root and run `.venv/Scripts/python.exe scripts/test_chat_live.py`. This reads real health/workflows and proposes then dismisses a recording segment; it does not start capture or a desktop run.


If the interface says **Connection unavailable**, reopen Melon Desktop; closing the native window also stops its backend. Do not use an old browser tab as a replacement for the desktop process. Chat reports lost connections and times out stalled requests. Desktop runtime errors are recorded locally in `.data/desktop-runtime.log`; `.data/desktop.log` records launcher failures. Before retrying a change after a connection error, check its page to avoid repeating an operation that may have completed.

## Automatic skill / workflow discovery

Open **Workflows** to see **Suggested workflows**, **Possible repeated tasks**, and **Most repeated tasks**. Discovery starts automatically 30 seconds after startup and runs every 30 minutes while Melon is open. **Check now** starts a scan without a manual history search. Closing Melon stops the worker; reopening retries interrupted work. Existing manual `/workflows/discover` and `/workflow-groups` remain compatible, but the Workflows suggestions now use the new persistent discovery service.

Configuration is in `.env.example`: `DISCOVERY_ENABLED`, `DISCOVERY_INTERVAL_MINUTES`, `DISCOVERY_STARTUP_DELAY_SECONDS`, `DISCOVERY_LOOKBACK_DAYS`, `DISCOVERY_CHUNK_HOURS`, `DISCOVERY_OVERLAP_MINUTES`, `DISCOVERY_SETTLE_SECONDS`, and confidence thresholds. Defaults inspect seven days in 24-hour chunks, with five-minute overlap and a one-minute indexing delay. Initial catch-up continues one chunk at a time between timer checks; subsequent regular scans inspect only new history plus overlap. A manual run starts one chunk and returns HTTP 202 immediately; poll `/discovery/status`. Failed or interrupted scans do not advance the cursor. Successful scans can have partial coverage, which is explicitly reported; the cursor means an interval was inspected, not that every frame was exhaustively reviewed. The overlap can miss records indexed very late. Change the overlap if your recorder indexes slowly.

The existing custom agent chooses dynamically discovered read-only Screenpipe MCP tools, with server-owned time bounds. It compares goals and action structures against saved semantic candidates, including singleton candidates held back until another occurrence appears. App names alone are not grouping keys. Original source frames, literal app/window metadata, and quoted timestamps are required. Discussion sources and activity summaries cannot establish repetitions. Shared source IDs, equal timestamps and overlapping same-app spans are conservatively deduplicated. Counts are distinct observed occurrences across retained scanned history; the UI does not label them as “this week” when they include older observations.

Pattern confidence is a model assessment, not a calibrated probability or coverage score. Below 0.65 stays hidden; 0.65–0.85 appears as possible repeated work; 0.85 and above appears as a stronger suggestion. Semantic interpretation still needs human review. First/last seen, apps, typical local hour and median observed elapsed span are computed from accepted source occurrences. Duration is unknown unless both endpoints have evidence; observed elapsed span is not active effort. Exact source excerpts remain available for inspection.

Patterns, original occurrences, source calls, decisions, drafts and scan progress persist atomically in `.data/discovery.json`. Dismissed suggestions stay dismissed when more members arrive. No large database or queue was added. Run one backend process per data directory. Background scans use your configured model provider and can incur its normal usage costs.

**Turn into workflow** compares every grouped occurrence and creates a draft. Each shared step and invariant historical value needs evidence from at least two occurrences. Changing inputs become required values; missing/masked details remain missing. Review the draft and explicitly click **Save workflow for review** to add it to the existing library. Saving or accepting a discovery never starts execution, creates a schedule, or bypasses existing desktop action approvals, stop or verification.

API:

- `GET /discovery/status`
- `GET /discovery/patterns?sort=frequent|recent|confidence&include_dismissed=false`
- `POST /discovery/run`
- `GET /discovery/patterns/{id}`
- `POST /discovery/patterns/{id}/accept`
- `POST /discovery/patterns/{id}/dismiss`
- `POST /discovery/patterns/{id}/create-workflow`
- `POST /discovery/patterns/{id}/save-workflow` with optional `title` and existing execution `defaults`

Validation: `.venv/Scripts/python.exe -m pytest -q` and `npm --prefix frontend run build`. Optional real history smoke: `.venv/Scripts/python.exe scripts/test_discovery_live.py --hours 8`. This uses isolated temporary storage, dynamically inspects MCP tools, records timing/coverage in ignored `artifacts/autonomous-discovery-live.json`, and never saves or executes a workflow. The exercised real scan completed in **39.934 seconds**, made 12 MCP reads, and returned **zero eligible patterns** with explicit partial coverage. Recorded activity existed; this result does not mean no tasks were performed. Populated grouping/draft/save behavior is covered by isolated tests, not claimed as a successful live multi-app discovery.
# Automatic memories and real page data

Melon now starts one background history sync two seconds after backend startup. It reuses the existing custom-agent discovery service and dynamically discovered Screenpipe MCP read tools. The first scan inspects the most recent day; later scans resume from the persisted cursor, with a five-minute overlap for context and deduplication. The default interval is 30 minutes. Scans run only while the app is open and may inspect a sample rather than every capture.

Home loads the latest indexed memories without requiring a search. Memories opens newest-first, supports local text/date/app/type filters, and automatically falls back to a deeper agent investigation when a submitted text search has no indexed match. **Search more Screenpipe history** also requests that investigation explicitly. Sufficiently anchored original search results join the durable index. Every task still requires explicit selection before reconstruction. Reconstructed indexed tasks remain reviewable after the temporary search cache expires.

Home, Memories and Settings show sync progress, last success, errors and a **Sync now** action. Settings also reads actual schedule-worker, recording, run, workflow and storage state. Workflows continues using real semantic patterns and explicitly saved workflows. Record, Schedule and Runs retain their existing persistence and execution flow; a segment stopped on Record opens its reconstructed draft when ready. Nothing automatically saves or executes a discovered workflow.

Additional configuration (see `.env.example`):

```dotenv
SYNC_STARTUP_DELAY_SECONDS=2
SYNC_INITIAL_LOOKBACK_DAYS=1
DISCOVERY_ENABLED=true
DISCOVERY_INTERVAL_MINUTES=30
```

The standalone discovery delay/lookback settings remain compatible with standalone discovery callers; the main app uses the `SYNC_` startup settings. Change `SYNC_INITIAL_LOOKBACK_DAYS` before the first scan to choose a wider initial window. Existing cursors are retained across restarts; changing initial lookback does not reset an existing cursor.

New APIs:

- `GET /sync/status`: actual job state, cursor, last success, counts, coverage notes and recovery warnings.
- `POST /sync/run`: starts/reuses a background scan, returns immediately with HTTP 202.
- `GET /memories`: public indexed occurrences, newest first. Optional `q`, `start_time`, `end_time`, `app`, `tag`, `source_kind`, `limit` (1–500), and `offset`. Time bounds require an offset/timezone; end is exclusive.
- `GET /memories/{id}`: a specific indexed occurrence and its evidence.
- `GET /system/activity`: actual scheduler, recording, run and workflow counts.

Memory IDs work with the existing `/tasks/{id}/reconstruct`, workflow review and explicit save endpoints. Existing routes remain compatible. Chat can read memories/sync status and propose sync through its existing confirmation flow.

Persistence uses `.data/memories.json` (public occurrence fields plus a private reconstruction ledger), `.data/sync_state.json`, and a derived `.data/patterns.json`. The existing `.data/discovery.json` remains authoritative for discovery occurrences, pattern identity, cursor and user decisions. On startup the app repairs derived projections from those records. Invalid memory-index JSON/schema is quarantined with its original bytes preserved and a visible recovery warning; source records are not silently replaced. Existing workflows, schedules, recordings and runs stay in their current stores. Use only one backend process per data directory.

Only exact original evidence supports indexed tasks. Different document edits and distant episodes remain separate occurrences; static duplicate frames cannot create repeated tasks. A visible test/demo edit can count, but an open file alone does not prove an edit or save. Empty indexed data does not mean the recorder has no history. Model confidence and inspected coverage are separate limitations. Relevant history is sent to the configured Azure/OpenAI provider during automatic sync.

Run the isolated timed integration check with:

```powershell
.\.venv\Scripts\python.exe scripts\test_memory_sync_live.py
```

It inspects actual recent Screenpipe history and preserves its private report and isolated JSON store under `artifacts/memory-sync-live*`; it does not save user workflows, create schedules or operate the desktop. Restart the desktop app after upgrading to load new backend routes. Reload alone updates frontend assets but cannot update an already-running Python backend. The Downloads Screenpipe backup has not been imported or substituted for the live recorder by this upgrade.



## Hackathon demo data

Close Melon and any backend before seeding or clearing. Activate `.venv`, then run `python -m scripts.seed_demo_data` or `python -m scripts.clear_demo_data`. Reopen Melon afterward. These commands write through the existing atomic JSON repository; they reject live supported server ports to avoid concurrent writes. `--data-dir` selects an alternate store (stop any custom-port server using it too).

Seeds three labeled memories/workflows, two initially disabled schedules, three explicitly simulated run records, and separate synthetic suggestion counts. Reseeding does not duplicate or reset existing examples. Cleanup removes only objects explicitly marked demo/seeded_demo. Existing real data and actual execution history remain intact. No Screenpipe discovery, email send, desktop execution, or enabled schedule is fabricated or initiated. See [demo validation](docs/DEMO_DATA.md) for exact contents, changed files and observed checks.


### Hackathon: seeded suggestions, real execution

Discovery examples may be seeded, but execution uses the same saved workflow, Azure agent, Zavora tools and supervised approval/verification gates. Review a suggestion, edit target/inputs, click **Approve workflow & values**, then **Start desktop run**. Editing requires approval again. Runs contains an event-backed final report and stored result review. Reopen Melon after this update.

The offline seed now creates no simulated run history and retires previously double-marked simulated runs while preserving real executions. See [demo flow and measured validation](docs/DEMO_DATA.md). Live isolated test: `.venv/Scripts/python.exe -m scripts.live_seeded_pipeline_test`; only a unique Notepad test document is edited, with narrowly scoped harness approval. Real test took 17.761s for execution, 21.708s including independent verification and feedback persistence. No live Gmail sending is claimed. Execution remains supervised and requires the app/backend and interactive desktop to remain available.


### Melonman workflow overlay

On Windows, workflow runs display the supplied transparent Melonman PNG sequence
from `assets/melonman_working/`, decoded once with built-in Windows GDI+.
No extra Python package is needed. The mascot is 64 logical pixels wide with a
soft yellow halo; its ten frames loop at 4 fps (2.5 seconds per loop).
The existing click-through, no-focus Win32 window, target messages and labels
are retained. Target bounds keep the character and label beside the control,
flipping to another side at monitor edges. Animation continues across movements.
A missing or invalid frame directory falls back to the original pointer.

Configure `AGENT_OVERLAY=false` to disable everything, or
`AGENT_OVERLAY_MASCOT=false` to use the original pointer. Set
`AGENT_OVERLAY_MASCOT_PATH`, `AGENT_OVERLAY_MASCOT_SIZE`, and
`AGENT_OVERLAY_MASCOT_FPS` as shown in `.env.example`. Restart Melon after changes.
The overlay is excluded from supported Windows screen captures and its existing
window title remains excluded by the Zavora desktop worker.

Headless checks: `.venv/Scripts/python.exe -m pytest tests/test_overlay.py tests/test_execution.py tests/test_desktop_app.py -q`.
Opt-in live diagnostics: `.venv/Scripts/python.exe -m scripts.melonman_overlay_smoke`.
That script uses an isolated Notepad fixture and storage, approves only its
expected edit, and records renderer previews and native placement observations
in `artifacts/melonman-overlay-smoke/`. Previews are the renderer's own transparent
surface, not screenshots with capture exclusion disabled.

### Sheets totals → PDF → WhatsApp (manual workflow)

The explicitly selected `sheets_totals_pdf_whatsapp_v1` execution mode keeps the fast six-column totals executor, then hands PDF export and WhatsApp Web document sending to the Azure desktop agent. The controlled phase selects and verifies the full `A1:G10` table. The export agent keeps existing PDF settings unchanged and only proceeds to Save; a physical-printer destination blocks execution. Chrome must be available and WhatsApp Web must already be signed in; the agent stops for QR login or an unavailable recipient.

Each run uses a named PDF on the actual Windows Desktop (including a redirected OneDrive Desktop), named `CA HT - Full table - YYYY-MM-DD_HH-MM-SS.pdf` with Europe/Paris date/time and no UUID. An existing filename is never overwritten. `verify_pdf_export` checks only that assigned file, validates PDF structure, page count and configured table labels, and records its hash. For an image-only print PDF, it requires the controlled live A1:G10 selection and explicitly reports that PDF cell text could not be independently read. The agent must verify the actual conversation number, the attachment filename and an outgoing Sent/Delivered/Read status; it must not resend after an uncertain outcome. Existing desktop approvals remain enabled. This mode is manual-only and still depends on live UI accessibility; a saved workflow is not proof of successful delivery. Install updated requirements and restart Melon to load the new backend. Review and approve the edited workflow before running it.

A saved `whatsapp_report` value adds a separate text report after verified PDF sending. `{pdf_filename}` is replaced with the actual dated filename. Completion requires both deliveries; the `verify_whatsapp_message` tool correlates each outgoing message with its own status instead of borrowing another message's timestamp/status. The saved report is editable and deliberately avoids unverified numeric totals.
