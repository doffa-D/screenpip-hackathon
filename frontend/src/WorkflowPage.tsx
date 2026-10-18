import type { ReactNode } from 'react'
import { useState } from 'react'
import { ArrowLeft, CalendarDays, Pencil, Play } from 'lucide-react'
import { api } from './api'
import { AppIcon, ApprovalBadge, date, DemoBadge, EmptyState, EvidenceList, human, LoadingState, RunRow, ScheduleRow, Section, Toggle } from './components'
import { href } from './routes'
import { WorkflowEditor } from './WorkflowEditor'
import type { Run, SavedWorkflow, Schedule, Task, Workflow } from './types'

const label = (name: string) => ({ recipient: 'Send to', subject: 'Subject', message_body: 'Message', starting_text: 'Original text', resulting_text: 'New text' }[name] || human(name))

export type WorkflowPageProps = {
  id: string; mode?: 'edit'
  saved: SavedWorkflow | null            // library hit; null renders the draft (unsaved task) variant
  task: Task | null; plan: Workflow | null
  ready: boolean; unavailable: boolean   // ready: draft state hydrated for this id
  values: Record<string, string>; setValues: (v: Record<string, string>) => void
  missing: Record<string, string>; setMissing: (v: Record<string, string>) => void
  instructions: string; setInstructions: (v: string) => void
  autoApprove: boolean; setAutoApprove: (v: boolean) => void
  approved: boolean; dirty: boolean
  busy: string; seconds: number; available: boolean
  save: () => void; approve: () => void; execute: () => void
  runs: Run[]; schedules: Schedule[]; activity: ReactNode
  openRun: (id: string) => void; toggleSchedule: (s: Schedule) => void
  edited: (w: SavedWorkflow) => Promise<void>; refresh: () => void | Promise<void>; go: (path: string, replace?: boolean) => void
}

export function WorkflowPage(p: WorkflowPageProps) {
  const { saved, task, plan, go } = p
  const [editor, setEditor] = useState<'title' | 'tags' | null>(null)
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(false)
  const back = () => window.history.length > 1 ? window.history.back() : go(href.workflows())
  if (p.unavailable && !saved) return <div className="workflow-page"><button className="link-button back-link" onClick={back}><ArrowLeft size={16}/> Back</button><EmptyState title="Workflow unavailable">It may have been archived or removed.</EmptyState></div>
  if (!task || !plan || !p.ready) return <div className="workflow-page"><button className="link-button back-link" onClick={back}><ArrowLeft size={16}/> Back</button><LoadingState title="Loading workflow" seconds={p.seconds}/></div>

  const missingRequired = plan.missing_values.some(k => !p.missing[k]?.trim())
  const editing = p.mode === 'edit' && !!saved
  const locked = !!p.busy || pending
  const myRuns = saved ? p.runs.filter(r => r.workflow_id === saved.id) : []
  const mySchedules = saved ? p.schedules.filter(s => s.workflow_id === saved.id) : []
  const demo = (saved?.origin ?? task.origin) === 'demo'
  const goal = plan.goal.toLowerCase().trim() !== task.title.toLowerCase().trim() ? plan.goal : ''
  const primary = !saved ? { text: 'Save', busyText: 'Saving…', busyKey: 'save', run: p.save, disabled: false }
    : !p.approved ? { text: 'Approve', busyText: 'Approving…', busyKey: 'approve-workflow', run: p.approve, disabled: missingRequired }
    : { text: 'Run', busyText: 'Starting…', busyKey: 'execute', run: p.execute, disabled: missingRequired || !p.available }

  async function saveMetadata() {
    if (!saved) return
    setPending(true); setError('')
    try {
      const change = editor === 'title' ? { title: input.trim() } : { tags: [...new Set(input.split(',').map(tag => tag.trim()).filter(Boolean))] }
      await api(`/workflows/${saved.id}`, { expected_revision: saved.revision, ...change }, 'PATCH')
      setEditor(null); void p.refresh()
    } catch (cause) { setError((cause as Error).message) } finally { setPending(false) }
  }
  async function archive() {
    if (!saved) return
    setPending(true); setError('')
    try { await api(`/workflows/${saved.id}`, {}, 'DELETE'); void p.refresh(); go(href.workflows()) }
    catch (cause) { setError((cause as Error).message) } finally { setPending(false) }
  }

  return <div className="workflow-page">
    <button className="link-button back-link" onClick={back}><ArrowLeft size={16}/> Back</button>
    <header className="workflow-head">
      <div className="workflow-title"><AppIcon title={task.title}/><h1>{task.title}</h1><ApprovalBadge approved={!!saved && p.approved} missing={missingRequired}/>{demo && <DemoBadge/>}</div>
      <p className="meta">{plan.steps.length} steps · {date(saved ? saved.updated_at : task.timestamp)}</p>
      {goal && <p className="workflow-goal">{goal}</p>}
      <div className="button-row workflow-actions">
        <button className="primary" disabled={locked || editing || primary.disabled} onClick={primary.run}>{p.busy === primary.busyKey ? primary.busyText : <>{primary.text}{primary.text === 'Run' && <Play size={15}/>}</>}</button>
        {saved && <>
          <button className="secondary" disabled={locked || editing} onClick={() => go(href.workflow(saved.id, true))}><Pencil size={15}/> Edit</button>
          <button className="secondary" disabled={locked} onClick={() => go(href.scheduleNew(saved.id))}><CalendarDays size={15}/> Schedule</button>
          <details className="workflow-more-actions"><summary>More</summary><div className="button-row">
            <button className="secondary" disabled={locked} onClick={() => { setEditor('title'); setInput(saved.title); setConfirmArchive(false) }}>Rename</button>
            <button className="secondary" disabled={locked} onClick={() => { setEditor('tags'); setInput(saved.tags.join(', ')); setConfirmArchive(false) }}>Tags</button>
            <button className="danger" disabled={locked} onClick={() => { setConfirmArchive(true); setEditor(null) }}>Archive</button>
          </div></details>
        </>}
      </div>
      {primary.text === 'Run' && !editing && (p.available
        ? <label className="auto-approve"><input type="checkbox" checked={p.autoApprove} disabled={locked} onChange={e => p.setAutoApprove(e.target.checked)}/><span>Auto-approve this run<small className="meta">{p.autoApprove ? ' · Melon will click and type without asking. You can still press Stop.' : ' · Otherwise each desktop change needs your approval.'}</small></span></label>
        : <small className="meta">Connect desktop control and finish any active run first.</small>)}
      {error && <p role="alert">{error}</p>}
      {editor && <form className="workflow-inline-editor" onSubmit={event => { event.preventDefault(); void saveMetadata() }}><label className="field"><span>{editor === 'title' ? 'Name' : 'Tags, separated by commas'}</span><input autoFocus value={input} maxLength={editor === 'title' ? 300 : 2000} onChange={event => setInput(event.target.value)}/></label><div className="button-row"><button className="primary" disabled={pending || (editor === 'title' && !input.trim())}>{pending ? 'Saving…' : 'Save'}</button><button className="secondary" type="button" disabled={pending} onClick={() => setEditor(null)}>Cancel</button></div></form>}
      {confirmArchive && <div className="workflow-inline-editor"><p>Archive “{task.title}”? It will be removed from the library.</p><div className="button-row"><button className="danger" disabled={pending} onClick={() => void archive()}>Archive</button><button className="secondary" disabled={pending} onClick={() => setConfirmArchive(false)}>Cancel</button></div></div>}
    </header>

    {!editing && p.activity}

    {editing && saved ? <WorkflowEditor key={saved.id} workflow={saved} cancel={() => go(href.workflow(saved.id), true)} saved={p.edited}/> : <>
      <Section title="Steps">
        {plan.steps.length ? <ol className="observed-steps">{plan.steps.map((step, i) => <li key={i}><span>{i + 1}</span><div><p>{step.description}</p>{step.evidence.length > 0 && <EvidenceList evidence={step.evidence}/>}</div></li>)}</ol> : <p className="meta">No steps yet.</p>}
      </Section>
      <Section title="Details">
        {Object.entries(plan.historical_values).map(([key, v]) => <div key={key}><label className="field"><span>{label(key)}</span><textarea value={p.values[key] ?? ''} maxLength={20000} rows={2} onChange={e => p.setValues({ ...p.values, [key]: e.target.value })}/></label>{v.evidence.length > 0 && <EvidenceList evidence={v.evidence}/>}</div>)}
        {plan.missing_values.map(k => <label className="field field-missing" key={k}><span>{label(k)}{!p.missing[k]?.trim() && <small className="required"> · Required</small>}</span><textarea rows={2} maxLength={20000} aria-required="true" value={p.missing[k] ?? ''} onChange={e => p.setMissing({ ...p.missing, [k]: e.target.value })}/></label>)}
        <label className="field"><span>App or window</span><textarea rows={3} maxLength={4000} value={p.instructions} onChange={e => p.setInstructions(e.target.value)} placeholder="Use the new Notepad document called Test.txt. Leave the original document unchanged."/></label>
        {saved && p.dirty && <button className="secondary" disabled={locked} onClick={p.save}>{p.busy === 'save' ? 'Saving…' : 'Save changes'}</button>}
      </Section>
    </>}

    {saved && !editing && <>
      <Section title="Previous activity">
        {myRuns.length ? <div className="item-list">{myRuns.map(r => <RunRow key={r.id} run={r} openRun={p.openRun}/>)}</div> : <p className="meta">No runs yet.</p>}
      </Section>
      <Section title="Schedules">
        {mySchedules.length ? <div className="item-list">{mySchedules.map(s => <ScheduleRow key={s.id} s={s} title={saved.title} openWorkflow={() => go(href.schedule(s.id))} trailing={<Toggle label={`Enable ${saved.title}`} checked={s.enabled} onChange={() => p.toggleSchedule(s)}/>}/>)}</div> : <p className="meta">Not scheduled.</p>}
      </Section>
    </>}

    <details className="section workflow-sources"><summary>Sources</summary>
      <p>{task.summary}</p>
      <small className="meta">{date(task.timestamp)}{saved ? ` · Version ${saved.revision}` : ''}</small>
      {plan.evidence.length > 0 && <EvidenceList evidence={plan.evidence}/>}
      {saved?.user_notes && <><h3>Notes</h3><p className="workflow-preserve-text">{saved.user_notes}</p></>}
      {saved && saved.tags.length > 0 && <div className="tags">{saved.tags.map(tag => <span key={tag}>{tag}</span>)}</div>}
    </details>
  </div>
}
