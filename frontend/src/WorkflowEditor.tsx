import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { api } from './api'
import { human, Section, text } from './components'
import type { SavedWorkflow } from './types'
import { workflowPlan } from './workflow-plan'

type Props = { workflow: SavedWorkflow; cancel: () => void; saved: (workflow: SavedWorkflow) => Promise<void> }

export function WorkflowEditor({ workflow: openedWorkflow, cancel, saved }: Props) {
  // Pin the version being edited so polling cannot bypass a stale-edit conflict.
  const [workflow] = useState(openedWorkflow)
  const plan = workflowPlan(workflow)
  const initial = {
    title: workflow.title, goal: plan.goal, steps: plan.steps.map(step => step.description),
    values: { ...Object.fromEntries(Object.entries(plan.historical_values).map(([key, value]) => [key, text(value.value)])), ...workflow.run_defaults.values },
    missing_values: { ...workflow.run_defaults.missing_values },
    instructions: workflow.run_defaults.instructions, notes: workflow.user_notes,
  }
  const [draft, setDraft] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial)
  const invalid = !draft.title.trim() || !draft.goal.trim() || !draft.steps.length || draft.steps.some(step => !step.trim())
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  function discard() { if (!busy && (!dirty || window.confirm('Discard your unsaved changes?'))) cancel() }
  function move(index: number, offset: number) {
    const steps = [...draft.steps]
    ;[steps[index], steps[index + offset]] = [steps[index + offset], steps[index]]
    setDraft({ ...draft, steps })
  }
  async function save() {
    if (busy || invalid) return
    setBusy(true); setError('')
    const definitionChanged = workflow.definition || draft.goal !== workflow.reconstruction.goal || JSON.stringify(draft.steps) !== JSON.stringify(workflow.reconstruction.steps.map(step => step.description))
    try {
      const updated = await api<SavedWorkflow>(`/workflows/${workflow.id}`, {
        expected_revision: workflow.revision,
        title: draft.title.trim(),
        ...(definitionChanged ? { definition: { goal: draft.goal.trim(), steps: draft.steps.map(step => step.trim()) } } : {}),
        run_defaults: { values: draft.values, missing_values: draft.missing_values, instructions: draft.instructions },
        user_notes: draft.notes,
      }, 'PATCH')
      await saved(updated)
    } catch (cause) { setError((cause as Error).message); setBusy(false) }
  }
  return <form className="workflow-detail workflow-editor" onSubmit={event => { event.preventDefault(); void save() }}>
    <Section title="Edit workflow" badge={<span className="badge">Re-approve after saving</span>}/>
    <fieldset disabled={busy}>
      <Section title="Name & goal">
        <label className="field"><span>Workflow name</span><input required maxLength={300} value={draft.title} onChange={event => setDraft({ ...draft, title: event.target.value })}/></label>
        <label className="field"><span>What should this task achieve?</span><textarea required maxLength={4000} rows={2} value={draft.goal} onChange={event => setDraft({ ...draft, goal: event.target.value })}/></label>
      </Section>
      <Section title="Steps">
        <ol className="workflow-edit-steps">{draft.steps.map((step, index) => <li key={index}>
          <label className="field"><span>Step {index + 1}</span><textarea required aria-label={`Step ${index + 1}`} maxLength={4000} rows={2} value={step} onChange={event => setDraft({ ...draft, steps: draft.steps.map((value, position) => position === index ? event.target.value : value) })}/></label>
          <div className="button-row"><button type="button" className="secondary" aria-label={`Move step ${index + 1} up`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={15}/> Up</button><button type="button" className="secondary" aria-label={`Move step ${index + 1} down`} disabled={index === draft.steps.length - 1} onClick={() => move(index, 1)}><ArrowDown size={15}/> Down</button><button type="button" className="danger" aria-label={`Remove step ${index + 1}`} disabled={draft.steps.length === 1} onClick={() => setDraft({ ...draft, steps: draft.steps.filter((_, position) => position !== index) })}><Trash2 size={15}/> Remove</button></div>
        </li>)}</ol>
        <button type="button" className="secondary" disabled={draft.steps.length >= 100} onClick={() => setDraft({ ...draft, steps: [...draft.steps, ''] })}><Plus size={15}/> Add a step</button>
      </Section>
      <Section title="Details">
        {Object.entries(draft.values).map(([name, value]) => <label className="field" key={name}><span>{human(name)}</span><textarea maxLength={20000} rows={3} value={value} onChange={event => setDraft({ ...draft, values: { ...draft.values, [name]: event.target.value } })}/></label>)}
        {plan.missing_values.map(name => <label className="field" key={name}><span>{human(name)} — needed before running</span><textarea rows={2} maxLength={20000} value={draft.missing_values[name] || ''} onChange={event => setDraft({ ...draft, missing_values: { ...draft.missing_values, [name]: event.target.value } })}/></label>)}
        {!Object.keys(draft.values).length && !plan.missing_values.length && <p className="meta">No extra details.</p>}
        <label className="field"><span>App or window</span><textarea rows={3} maxLength={4000} placeholder="For example: Use Gmail in the open Google Chrome tab. Prepare a draft for me to review." value={draft.instructions} onChange={event => setDraft({ ...draft, instructions: event.target.value })}/></label>
        <label className="field"><span>Your notes (optional)</span><textarea rows={2} maxLength={10000} value={draft.notes} onChange={event => setDraft({ ...draft, notes: event.target.value })}/></label>
      </Section>
    </fieldset>
    <div className="section workflow-edit-footer">
      {error && <p role="alert">{error}</p>}
      <div className="button-row"><button className="primary" disabled={busy || invalid || !dirty}>{busy ? 'Saving…' : 'Save changes'}</button><button className="secondary" type="button" disabled={busy} onClick={discard}>Cancel</button></div>
      <p className="footnote">Existing schedules keep their older saved version. Create a new schedule if you want it to use these changes.</p>
    </div>
  </form>
}
