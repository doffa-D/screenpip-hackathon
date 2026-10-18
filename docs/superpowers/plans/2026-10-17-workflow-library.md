# Workflow library and detail view implementation plan

**Goal:** Show every saved workflow in a compact library and move all management actions inside the selected workflow.

**Architecture:** Keep existing API models, revision guards, review, approvals and execution. Add a dedicated React library/detail component with explicit hash routes. Pass the selected workflow to the existing schedule form.

**Tech Stack:** React, TypeScript, existing CSS and FastAPI APIs.

**Spec:** User request in this conversation, 2026-10-17.

## Constraints
- Preserve all saved data and existing execution approval behavior.
- No automatic selection, execution or schedule creation.
- All workflows means the full active library; archived workflows remain archived.

## Tasks
- [x] Extract the library from memory-pages.tsx into Workflows.tsx. Default to a searchable full library with one open action per row; keep discovery on separate tabs.
- [x] Add workflows/view/{id}, resolving only the selected ID. Show all steps, effective defaults, missing values, instructions, notes and evidence. Move Review & run, Rename, Schedule, Edit tags and Archive here. Use existing PATCH/DELETE APIs and surface errors.
- [x] Pass schedule/{id} into SchedulePage to preselect the actual saved workflow without creating a schedule.
- [x] Build TypeScript/Vite and browser-check library selection, full details, navigation, editing and responsive overflow with an isolated copy of existing data. Do not run workflows or modify user data.

Validation: production TypeScript/Vite build and 81 existing backend tests passed. Browser used isolated copy artifacts/workflow-library-qa/state: full list, selected Notepad detail, rename persisted, tag dedup persisted, exact workflow schedule selection, review with all four steps, archive returned to two-row library, no-match search. No actual execution/schedule creation and no user store changes. Desktop overflow checked. Resize tool retained a 1536px viewport, so mobile behavior is not claimed as browser-tested.
