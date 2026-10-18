import { CheckCircle2, LoaderCircle, Square } from 'lucide-react'
import { active, date, duration, human, StatusBadge, text } from './components'
import { RunReport } from './RunReport'
import type { Run } from './types'

type Props = {
  run: Run; busy: boolean
  decide: (approve: boolean) => void; stop: (id?: string) => void
  feedback: (verdict: 'looks_good' | 'something_wrong', notes: string) => void
}

export function WorkflowActivity({ run, busy, decide, stop, feedback }: Props) {
  const working = active(run.status)
  const events = run.events ?? []
  const latest = events.at(-1)
  return <section className="section workflow-activity" aria-label="Workflow activity">
    <div className="section-heading"><h2>{working ? 'Working on your workflow' : 'Workflow result'}</h2><StatusBadge status={run.status}/></div>
    <p className="workflow-live-state" role="status">{working && <LoaderCircle size={17} className="activity-spinner"/>}{run.status === 'awaiting_approval' ? 'Your approval is needed to continue.' : working ? latest?.title ?? 'Starting your workflow…' : run.summary}</p>
    <small className="meta">Started {date(run.started_at)}{run.elapsed_seconds != null && ` · ${duration(run.elapsed_seconds)}`}</small>
    <h3>Activity</h3>
    <p className="meta">Live actions and checks from this run. The planned steps below are your instructions.</p>
    <ol className="workflow-activity-list" aria-label="Live workflow steps">{events.map((event, index) => {
      const detail = event.detail as Record<string, unknown> | null
      const reason = detail && typeof detail.reason === 'string' ? detail.reason : ''
      return <li key={event.id} className={working && index === events.length - 1 ? 'is-current' : ''}>
        <span className="activity-marker">{event.kind === 'verified' ? <CheckCircle2 size={16}/> : index + 1}</span>
        <div><strong>{event.title}</strong>{reason && <p>{reason}</p>}<time>{date(event.timestamp)}</time></div>
      </li>
    })}</ol>
    {!events.length && <p className="meta">Waiting for the first activity update…</p>}
    {run.pending_action && run.status === 'awaiting_approval' && <section className="approval"><h3>Review this change</h3><p>{String(run.pending_action.arguments.reason || 'Melon needs your approval for the next action.')}</p><dl>{Object.entries(run.pending_action.arguments).filter(([key]) => ['window_title', 'url', 'value', 'label', 'action'].includes(key)).map(([key, value]) => <div key={key}><dt>{human(key)}</dt><dd className="workflow-preserve-text">{text(value)}</dd></div>)}</dl><div className="button-row"><button className="secondary" disabled={busy} onClick={() => decide(false)}>Decline</button><button className="primary" disabled={busy} onClick={() => decide(true)}>Approve and continue</button></div></section>}
    {working && <button className="danger" disabled={busy || run.status === 'stopping'} onClick={() => { if (window.confirm('Stop this workflow? Changes already made are not undone.')) stop(run.id) }}><Square size={15}/>{run.status === 'stopping' ? 'Stopping…' : 'Stop workflow'}</button>}
    <RunReport key={run.id} run={run} feedback={feedback} busy={busy}/>
    <details><summary>Technical details</summary><pre>{JSON.stringify(events, null, 2)}</pre></details>
  </section>
}
