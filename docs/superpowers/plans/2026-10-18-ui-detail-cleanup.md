# UI Detail Cleanup Implementation Plan

**Goal:** Keep Melon simple while correcting spacing, text density and oversized actions seen in the six screenshots.
**Architecture:** Adjust existing shared CSS and scoped card styles; preserve navigation and behavior.
**Tech Stack:** React, TypeScript, CSS, Vite.
**Spec:** User request: improve the UI without making it complex; fix messy details.

- [x] Add consistent page gutters and header height in styles.css.
- [x] Allow memory descriptions two lines and improve row line height.
- [x] Size schedule and Night shift actions to their labels; keep cards aligned at the top.
- [x] Improve muted text contrast through existing theme tokens.
- [x] Clarify the empty schedule preview message in support-pages.tsx.
- [x] Build the frontend and inspect all six desktop routes; no horizontal overflow. Reviewed updated Memories and Schedule screenshots. Narrow viewport verification was unavailable because browser tools stopped responding.

