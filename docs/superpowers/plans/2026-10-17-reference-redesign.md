# Recall Reference Redesign Implementation Plan

> **For agentic workers:** Execute this plan task-by-task inline in the current session.

**Goal:** Match the seven supplied Recall references while preserving live historical search and approved desktop replay.
**Architecture:** Shared React shell, reusable visual primitives, separate page components, typed API and application state. Unsupported recording/scheduling remain explicitly isolated local demos; no pretend capture or automatic desktop actions.
**Tech Stack:** React, TypeScript, Vite, Lucide, CSS.
**Spec:** C:/Users/Doffa/.codex/attachments/7e388e80-6373-4619-afbe-bf1b9ff70b44/Pasted text.txt

## Global Constraints
- Never auto-select a historical task. Keep each occurrence separate.
- Preserve evidence, missing values, exact approval, stop, and verification.
- No technical tool details outside expandable diagnostics.
- Demo schedules never execute; demo recording only marks a local time segment.
- Never fabricate confidence, repetition counts, successful verification, or connection readiness.

### Task 1: Shell and visual system
- [ ] Create shared sidebar, wave header, search, cards, evidence, badges and accessible dialogs in frontend/src/components.tsx.
- [ ] Replace frontend/src/styles.css with responsive lavender/blue design tokens and reduced-motion rules.
- [ ] Use hash navigation for all seven pages and workflow/run details; direct reload remains compatible with existing FastAPI root.

### Task 2: Live memory and workflow flow
- [ ] Replace App.tsx state controller, preserve existing API routes and only edited value overrides.
- [ ] Build Home, Memories, Workflows, review and Runs pages with explicit selection and factual evidence.
- [ ] Render readable approvals, raw details collapsed, active-run recovery and stop controls.

### Task 3: Supporting experiences
- [ ] Add isolated persistent local demo schedules with create/edit/delete/pause and recurrence preview.
- [ ] Add local segment demo timer, markers, in-app shortcuts, honest capture limitations.
- [ ] Add settings health checks, real desktop probe, local appearance and notification preferences.

### Task 4: Verification
- [ ] Run TypeScript/production build and backend tests.
- [ ] Inspect actual browser at desktop and narrow widths; check all routes and console.
- [ ] Test search, selection/review and approval UI against isolated browser fixtures without mutating the desktop.
- [ ] Document demos and remaining backend gaps in README.
