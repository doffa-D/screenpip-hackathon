# Reference UI Implementation Plan

> **For agentic workers:** Execute inline in this session, task by task.

**Goal:** Match the seven supplied reference images across the existing Melon desktop interface.

**Architecture:** Add one scoped visual theme after existing styles, update the shared header with local SVG waves and restore the Home headline. Preserve all live API bindings, Chat, discovery, recording timestamps, review and approval controls.

**Tech Stack:** React, TypeScript, CSS, local inline SVG, Vite.

**Spec:** User's seven reference images attached in this conversation.

## Global Constraints

- Preserve Melon branding and real data; no fabricated tasks, statuses or decorative controls presented as functioning features.
- Indigo/violet accent, pale blue canvas, translucent sidebar, navy headings, white rounded cards, flowing hero backgrounds.
- Keep responsive layouts, accessible focus, reduced motion and existing dark appearance.

### Task 1: Shared visual system

**Files:** Modify `frontend/src/components.tsx`, `frontend/src/App.tsx`, `frontend/src/main.tsx`; create `frontend/src/reference-theme.css`.

- [x] Add decorative SVG waves to PageHeader and retain its title/subtitle/children interface.
- [x] Restore the reference Home headline and style the shared shell, sidebar, hero, cards, buttons, forms and detailed panels.
- [x] Apply the same system to Chat, workflow discovery, recording, schedules, runs and settings without replacing their live controls.
- [x] Preserve dark/system appearance and narrow-window navigation; respect reduced motion.

### Task 2: Verification and handoff

**Files:** Update `docs/HANDOFF.md`; build `frontend/dist`.

- [x] Run `npm run build` in frontend and resolve compiler errors.
- [x] Inspect actual local app Home and feature routes in a separate browser tab; check desktop and narrow-screen overflow, then inspect screenshots.
- [x] Record actual verification results and reload instructions in the handoff.

No backend contract changes or new dependencies are needed. Visual checks and compilation are appropriate for this reversible presentation-only change.
