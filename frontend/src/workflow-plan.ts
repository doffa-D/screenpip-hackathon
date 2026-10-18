import type { SavedWorkflow, Workflow } from './types'

export function workflowPlan(workflow: SavedWorkflow): Workflow {
  if (!workflow.definition) return workflow.reconstruction
  return {
    ...workflow.reconstruction,
    goal: workflow.definition.goal,
    steps: workflow.definition.steps.map(description => ({ description, evidence: [], source: 'user' })),
  }
}
