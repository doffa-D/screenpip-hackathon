# Screenpipe Agent Implementation Plan

**Goal:** Find distinct historical task occurrences and reconstruct only a user-selected task.
**Architecture:** FastAPI creates a request-scoped stdio MCP session. A custom OpenAI tool loop discovers Screenpipe schemas, gathers evidence, and returns Pydantic-validated output. Tasks and their evidence remain in bounded process memory.
**Tech Stack:** Python 3.12, FastAPI, MCP SDK, OpenAI SDK, Pydantic.
**Spec:** User requirements in this chat.

## Constraints
No Pi, frontend, SQLite, execution, coordinates, automatic task selection, or invented history. Preserve original evidence and distinct occurrences.

## Tasks
- [x] Build configuration, structured models, and reusable timeout-aware MCP connection in backend/config.py, models.py, mcp_client.py.
- [x] Inspect the actual stdio server with scripts/probe_mcp.py; record tool schemas and enable only verified read tools in backend/screenpipe_tools.py.
- [x] Build iterative tool reasoning and evidence validation in backend/agent.py; wire search, selection, health, retention and error handling in backend/main.py.
- [x] Add mocked multi-turn regression tests and run the real MCP probe and an HTTP search smoke test. Document credential or recorder blockers accurately.
- [x] Deliver requirements.txt, .env.example, README.md with local run instructions.

Execution is inline under the user's request to implement the project.
