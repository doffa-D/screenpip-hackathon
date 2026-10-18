# Melonman Overlay Implementation Plan

> Execute inline in the current session; the user has authorized implementation and a real smoke test.

**Goal:** Replace the glowing pointer with the supplied transparent Melonman frames without changing execution approvals or Zavora integration.

**Architecture:** Retain the UDP messages, separate Win32 process, window title/styles and label. Decode the supplied PNG sequence once with Windows GDI+, cache premultiplied frames, and animate on a monotonic clock independently of movement. No additional package is required.

**Spec:** C:/Users/Doffa/.codex/attachments/f9871a25-ee22-4de7-ae21-e0ba4d44f12d/Pasted text.txt

## Constraints

- Preserve master off switch, no activation, click-through, enumeration exclusion, approvals and target coordinate scaling.
- Missing/corrupt assets fall back to the original pointer.
- Use target bounds to place the mascot and label outside the control and clamp to the target monitor.
- Keep tests headless. Perform a separate explicitly authorized live smoke test with an isolated harmless workflow.

## Tasks

- [x] Add config fields in backend/config.py, pass them into backend/overlay.py from backend/execution.py, document .env.example.
- [x] Add backend/overlay_mascot.py: pure placement/frame-clock helpers and native GDI+ PNG frame decoding; extract assets/melonman_working/*.png from the provided archive.
- [x] Adapt backend/overlay_window.py render/tick only: cache a label surface, composite unchanged-color frames, glide with existing easing, preserve animation epoch across messages.
- [x] Extend aim() messages with bounds while retaining existing at coordinates. Preserve window title filtering and all existing desktop action behavior.
- [x] Add tests/test_overlay.py for configuration, off/fallback, geometry/edges/target separation, frame clock, status, lifecycle and native frame decoding without opening windows.
- [x] Run relevant tests, inspect runtime and perform one isolated real workflow smoke test; capture placement/transparency and report evidence and any limitations.

Validation commands: `.venv/Scripts/python.exe -m pytest tests/test_overlay.py tests/test_execution.py tests/test_desktop.py tests/test_desktop_app.py -q`; `.venv/Scripts/python.exe -m compileall -q backend`.


## Result and validation

- User subsequently requested large-cursor size, slower playback and yellow glow: defaults now 64 logical pixels, 4 fps, cached soft yellow halo. Original mascot colors preserved.
- 30 targeted tests passed; Python compilation passed.
- Real Azure/Zavora isolated workflow completed in 41.216 seconds: run `ee94509c-c88e-4918-a740-22a1edda519a`, two approved fixture edits, independent exact-value verification. Evidence: `artifacts/seeded-real-execution/c919b8f7052b/validation.json`.
- Diagnostic repeat observed all ten animated frames, mascot loaded, unchanged foreground window across overlay ticks, native extended style 134742184 and capture affinity 17 (WDA_EXCLUDEFROMCAPTURE). Recorded target bounds placed the entire 619x246 surface above the editor with a gap. These measurements predate the requested smaller/slower visual adjustment.
- Diagnostic repeat stopped when the model proposed an unexpected action; fixture harness declined it. Do not describe that repeat as completed. Concurrent desktop activity makes further live mutation testing unsuitable in this session.
- Target-window capture intentionally omitted the mascot; transparent renderer previews (`act.png`, `think.png`, `wait.png`) were inspected separately. Screen-edge behavior covered by headless geometry tests, not a live multi-monitor edge capture.
- Existing test isolation allowed fresh Settings() to spawn overlay processes; conftest now sets AGENT_OVERLAY=false. Fixed existing no_sleep mock to yield, avoiding a busy-loop deadlock in the open_url approval test.

Modified implementation files: backend/config.py, backend/overlay.py, backend/overlay_window.py, backend/execution.py. Added backend/overlay_mascot.py and assets/melonman_working/*.png. Updated .env.example, README.md, tests/conftest.py, tests/test_execution.py; added tests/test_overlay.py and scripts/melonman_overlay_smoke.py.
