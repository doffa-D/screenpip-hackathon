# Zavora Executor Implementation Plan

**Goal:** Replace the running app's xa11y executor with local Zavora MCP.

**Architecture:** Preserve the existing approved-action state machine. Expose a
small validated adapter over Zavora's discovered accessibility tools. Execute
each MCP operation in an isolated worker and terminate its process tree on stop.

**Tech stack:** Python/FastAPI, MCP stdio, Zavora 7.6.1, React/TypeScript.

- [x] Replace desktop schemas with window IDs, exact titles, roles and labels;
  require fresh unique-element resolution before mutation and verification.
- [x] Replace native worker with an MCP worker; preserve approval and verification
  gates in execution.py using window identity rather than process identity.
- [x] Update health, frontend text, setup instructions and real API replay test.
- [x] Run approval/cancellation/ambiguity tests, build frontend, perform the
  explicitly selected Notepad replay through Azure and Zavora, record timings.

Files: backend/desktop.py, desktop_worker.py, execution.py, main.py;
frontend/src/App.tsx; tests/test_execution.py; scripts/live_execute_test.py;
README.md. Keep Screenpipe search and saved workflows compatible. No automatic
task selection, coordinates, shell tools or unapproved desktop mutations.
