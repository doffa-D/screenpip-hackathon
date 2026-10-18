# Inline Workflow Activity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Remove Runs and Settings pages from navigation and keep live execution, approvals, stopping, and reports inside each workflow.

**Architecture:** Reuse the existing persisted run events and one-second polling. Render a focused activity component inside WorkflowPage. Resolve old run links to their owning workflow; retain backend settings and run APIs.

**Tech Stack:** React, TypeScript, FastAPI (unchanged).

**Spec:** User request: remove runs/settings and display working steps in the workflow window.

## Global Constraints
- Preserve real event data and approval behavior; do not invent completed workflow steps.
- Do not execute or send emails for UI validation.
- Keep existing data and unrelated workspace edits.

### Task 1: Inline activity and navigation
**Files:** Create frontend/src/WorkflowActivity.tsx; modify App.tsx, WorkflowPage.tsx, components.tsx, Chat.tsx, reference-theme.css.
- [x] Add an inline component consuming Run, decide, stop, feedback; list real event titles/reasons and timestamps, show pending approval controls and RunReport.
- [x] Keep execute on workflow route; open historical runs there; load latest associated run on reopening and poll active runs.
- [x] Remove Runs/Settings entry points and redirect legacy routes. Show all workflow-specific history locally.
- [x] Build with `npm run build` in frontend; fix TypeScript failures.
- [x] Validate read-only UI navigation and live-event rendering without desktop mutations; document verification and limitations in docs/HANDOFF.md.
