# Reference redesign and real features — October 17, 2026

Latest implementation replaces the unfinished frontend source with seven working pages. No seeded product tasks/schedules/repeat counts were added.

- Backend suite: **31 passed**; TypeScript/Vite production build passed.
- Browser checked all seven routes at 1536px desktop and 390px phone widths: headings rendered, no horizontal overflow or error banners. Home screenshot inspected against the references. Tests cover API/state behavior; they are not a claim that every visual interaction was manually exercised.
- Live provider connection: Azure responded in **1.761s**. Zavora window enumeration: **2.600s**. Screenpipe MCP reached the local recorder; its payload reports **degraded** capture health (audio warning), now shown separately from connection reachability. Repeat health check **2.109s**.
- Real saved workflow execution: task cache cleared after saving, then Azure + Zavora changed only a new Notepad fixture. **22.090s** through completion polling; backend execution **21 events**, completed. Independent fresh MCP verification confirmed exact `hello world`. Full preparation plus independent verification **26.520s**.
- Timestamp recording of that interval reconstructed in **18.573s**. Real quotes recovered the test document/final text; missing edit/keystroke evidence was kept explicit. This verifies bounded retrieval and honest reconstruction, not capture of every input event.
- Near-term one-time schedule: **28.045s including the scheduled wait**, exactly **one occurrence**, reached explicit approval, completed with live verification. Temporary schedule removed. Daily/weekly/monthly/DST calculations and missed/restart behavior have focused tests; those recurrences were not each waited out live.
- Live repeated-task discovery over four hours: **41.031s**, one group containing **two original-evidence Notepad occurrences**. Explicit partial-coverage notes; each member remains addressable. This does not prove exhaustive counting.
- Live sent-email search with Today/Email filters: first attempt exhausted its budget due to offering frame tools without enforceable time bounds. Restricted offered tools to dynamic time-bound schemas; retry **HTTP 200, [] in 43.170s**. No verified sent-email matches found; this is not proof no emails were sent.
- Global Windows shortcuts all registered. From a focused isolated Notepad window, Ctrl+Shift+R created a persisted start timestamp, Ctrl+Shift+M created a real marker, and Ctrl+Shift+R fixed the end timestamp and started processing. Capture health was reported as degraded. No Screenpipe recording switch or input capture hooks were used.
- Browser recording → explicit review → durable save → URL reload passed; test workflow archived afterward. Persisted dark appearance applied after reload and original preferences were restored.
- No email sending, public posting, original-document overwrite or deletion tested.

Private artifacts: `artifacts/real-features/connections.json`, `email-search-retry.json`, `discovery.json`, and `live/{run,recording,scheduled-run,timings}.json`. Earlier results below are historical and do not describe the current UI.

---

## Zavora executor replacement — October 17, 2026

- Runtime desktop executor now uses @zavora-ai/computer-use-mcp@7.6.1 over stdio.
- Real selected 20:03 Notepad workflow replayed through Azure + actual API + Zavora.
- New fixture only; exact fixture-scoped set_value approved by the test harness.
- Completed in 19.356 seconds, 20 run events. Separate MCP session confirmed hello world.
- Report: artifacts/full-app-live/run.json. Test tab left open, edit not saved.
- 20 automated tests passed, including approval/decline/stop, process-tree timeout,
  changed-window identity rejection and ambiguous/substring target rejection.
- React/TypeScript production build passed.
- No xa11y runtime dependency. Earlier results below are historical comparisons.

# Full application verification — 2026-10-17

- React + TypeScript production build passed with Vite 8.3.4. npm installation audit reported zero vulnerabilities.
- Backend regression/state-machine suite: **15 passed**. Includes approval replay rejection, decline/stop before mutation, verification gating, one active run, missing values, interrupted recovery, native timeout kill, ambiguous-element rejection, origin/Host checks and atomic persistence.
- Real Azure + xa11y execution through FastAPI: **completed in 8.411 seconds**. Used the previously explicitly selected 20:03 Notepad occurrence and a uniquely named NEW fixture. Approved only its exact set_value to hello world; independently read final UI text. Report: `artifacts/full-app-live/run.json`.
- Real browser flow on the built frontend: search returned **2 distinct Notepad occurrences in 18.3 seconds**; selected the previously user-chosen 20:03 occurrence; reconstruction returned 3 observed steps and 2 explicit gaps. Filled gaps with instructions not to save and not to reproduce unknown keystrokes. Started execution, reviewed exact window-scoped selector and hello world value, approved, and observed **Completed** with 17 timeline events. Total **36.7 seconds including human review time**. Independent xa11y read confirmed hello world; no save tested.
- Saved tasks and reconstructed workflow survived stopping/restarting the backend before execution. Separately loaded JSON state contained 2 tasks, 1 reconstruction and 1 completed UI run.
- UI checked in the in-app browser at its narrow viewport: search, loading state, result cards, reconstruction inputs, disabled start until gaps filled, approval, completion and run-history views. Screenshot: `artifacts/full-app-live/frontend-completed.png`. Desktop/wide layout uses responsive CSS but was not visually inspected in a wide browser viewport.
- First isolated replay was correctly declined by the test harness because the agent proposed a selector without the unique fixture window. Tool guidance now includes CSS selector examples, and runtime validation requires named-window/dialog scope on mutations. The repeated real test passed.
- Desktop support is verified for this Windows Notepad version. Other apps/actions depend on their accessibility provider. No email sending, public submission, shell execution, or unattended multi-app workflow was tested. The model still chooses semantic verification targets; exact text checks are additional enforcement, not a universal proof of task correctness.
- Native calls are bounded and killed on timeout/cancel. Already-applied UI changes are not rolled back. Approval wait counts toward the 600-second execution limit.

---

# Verification — 2026-10-17

## Latest live Azure results

After the user authorized using configuration from the neighboring Hackathon
project, the required Azure settings were copied into ignored local `.env`.
The deployed `gpt-6-luna` model required `REASONING_EFFORT=none` for Chat
Completions tool calls. This was verified against the actual Azure API and added
as an optional model setting. No credentials were printed.

Real calls through the actual FastAPI routes, real Azure model and stdio MCP:

- Sent-email search today: initially exhausted 12 rounds. Reserving the last
  round for an answer fixed the non-terminating-search behavior. Retest returned
  HTTP 200 and `[]`; no supported sent-email occurrences found within the bounded
  investigation. This does not prove there were no sent emails.
- Notepad search yesterday: HTTP 200, initially two distinct editing occurrences
  around 19:56 and 20:03, with summaries and exact original quotes. Another broad
  retest grouped these as one editing session: grouping remains model-dependent.
  An explicit search for the two separate observed occurrences returned two.
- Today's activities with summaries: HTTP 200, four candidates. One title
  overstated implementation from chat evidence. The instruction was tightened to
  label observed discussions as discussions, not verified implementation. That
  broad four-candidate output has not been revalidated with the revised prompt.
- File Explorer occurrence: HTTP 200, one original observed occurrence browsing
  the Hackathon/backend folder.
- User explicitly selected the 20:03 hello-world edit. Reconstruction returned
  HTTP 200, using fresh MCP reads plus the selected occurrence's stored evidence.
  It identified `hello wor` at 20:03:38.612804600+02:00 and `hello world` at
  20:03:40.194125500+02:00, with exact frame/document quotes. Specific keystrokes
  were marked unobserved rather than invented. No execution was performed.

Latest real outputs: `artifacts/email-final/`, `artifacts/notepad-occurrences/`
(search-1.json, workflow.json, session.json and tool-trace.log). The harness uses
ASGI TestClient to call real routes; model and MCP dependencies are not mocked.
The test-only saved session lets an explicitly selected task be reconstructed
across harness runs without adding persistence to the backend itself.

## Initial setup checks and earlier blockers

- Created Python 3.12 virtual environment and installed dependencies. Exact tested
  environment is recorded in `requirements.lock.txt` (Windows/Python 3.12).
- Launched the actual `npx -y screenpipe-mcp@latest` stdio server, version 0.20.3.
  MCP initialize and tools/list succeeded: 33 tools. Full discovered schemas are
  in `mcp-tools.json`. Names and input schemas were inspected before integration.
- Called `health-check`: recorder reachable, version 0.4.52, status `degraded`.
- Called `search-content` for today's local day, original screen content,
  limit 1: completed without an MCP tool error. This is a transport/read smoke
  check, not a natural-language email search or a completeness claim.
- Six automated tests passed: iterative search with two original occurrences,
  fabricated-quote rejection, write-tool rejection, HTTP search and unknown
  selection, selected reconstruction, and missing-credential handling.
- Started Uvicorn on localhost:8000. GET /health returned 200.
- Sent actual POST /tasks/search with `Find all emails I sent today`:
  HTTP 503 with actionable missing Azure configuration detail. No model keys,
  endpoint or deployment were configured. A successful live model-led search
  could not be verified; fill `.env` and run `scripts.smoke_search` to finish it.
- One successful recorder probe emitted a Node/libuv Windows shutdown assertion
  after calls completed. Treat recurring subprocess exit issues as dependency
  failures; do not infer that the recorder returned no matching history.
- A repeat read exposed invalid lone-surrogate JSON from Screenpipe's server-side
  text truncation. The adapter now requests untruncated search-content text with
  at most 20 rows and applies the model text budget locally after decoding.

Scripted model tests verify orchestration and response contracts, not live model
accuracy or whether this recorder contains sent-email evidence.

## Additional real-data test

`python -m scripts.live_test` called real Screenpipe activity-summary and
search-content successfully. The returned summary covered October 17 from local
midnight to 09:41, reported data status ok and 16.9 authoritative active minutes.
The original-content query returned five of 431 matching screen records, including
File Explorer frames. These are limited samples, not reconstructed workflows.

Three actual FastAPI route calls (ASGI TestClient, no mocked dependencies) asked
for sent emails today, Notepad tasks yesterday, and today's distinct tasks with
summaries. All returned HTTP 503 due to absent model configuration. Real responses
and recorder data are saved locally in ignored `artifacts/live-test/`. No workflow
was invented or automatically selected; model-backed reconstruction remains
untested until credentials and an explicit task selection are available.

## Desktop conversion — October 17, 2026
Actual Edge WebView2 window smoke passed: seven rendered routes and six real local API endpoints HTTP200. Test closed native window and verified owned port8765 released. No demo data or desktop task changes performed. Backend regression suite33passed; production frontend build passed. Original web process stopped after confirming no active runs/enabled schedules. Desktop shortcut installed. Source-installed Windows app; standalone installer, native notifications and background tray service are not implemented.
