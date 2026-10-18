# Editable saved workflow implementation plan

**Goal:** Let users edit a saved workflow's goal, steps, inputs, instructions and notes, retaining original history and existing approvals.

- [x] Add validated user-authored definition to saved workflow/update models, separate from reconstruction. Materialize an execution plan only for saved execution; preserve original evidence rules for model reconstruction.
- [x] Add simple editor with step add/remove/reorder, goal/name, saved inputs and instructions; optimistic revision guard, save/cancel, missing detail validation and reapproval explanation.
- [x] Test persistence, stale edit rejection, original evidence preservation, user plan reaching execution and approval invalidation. Build frontend and check editor in isolated copied data.
