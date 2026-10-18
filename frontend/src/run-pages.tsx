import { RunReport } from './RunReport'
import { useState } from 'react'
import { Square, X } from 'lucide-react'
import type { Run } from './types'
import { workflowRef, type WorkflowRef } from './routes'
import { active, date, DemoBadge, duration, EmptyState, human, PageHeader, RunRow, StatusBadge, text, WorkflowLink } from './components'

const statuses = ['running', 'awaiting_approval', 'completed', 'blocked', 'failed', 'cancelled', 'interrupted']

export function Runs({ loaded, loadError, runs, run, feedback, openRun, openWorkflow, decide, stop, busy, close }: {loaded:boolean;loadError:string;runs: Run[]; run: Run|null; feedback:(verdict:'looks_good'|'something_wrong',notes:string)=>void; openRun:(id:string)=>void; openWorkflow:(ref:WorkflowRef)=>void; decide:(v:boolean)=>void; stop:(id?:string)=>void; busy:boolean; close:()=>void}) {
  const [query,setQuery]=useState(''); const [status,setStatus]=useState('')
  const confirmStop=(id:string)=>{ if(window.confirm('Stop this run? Future actions will not happen. Changes already made are not undone.')) stop(id) }
  const current = runs.find(r=>active(r.status))
  const rows = runs.filter(r=>(!status||r.status===status)&&r.title.toLowerCase().includes(query.toLowerCase()))
  const pinned = current
  const rest = pinned ? rows.filter(r=>r!==pinned) : rows
  return <>
  <PageHeader title="Runs"/>
  <div className="page-data-state">{!loaded&&<p role="status">Loading run history…</p>}</div>
  <div className={`split-layout ${run ? 'has-detail' : ''}`}><div>
    <div className="filters"><input aria-label="Search runs" placeholder="Search runs…" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="Run status" value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option>{statuses.map(s=><option key={s} value={s}>{human(s)}</option>)}</select></div>
    {pinned&&<div className="run-pinned"><RunRow run={pinned} openRun={openRun}/><div className="indeterminate" role="progressbar" aria-label="Desktop workflow in progress"/><div className="button-row"><button className="danger" onClick={()=>confirmStop(pinned.id)}>Stop run</button></div></div>}
    {rest.map(r=><RunRow key={r.id} run={r} openRun={openRun}/>)}
    {loaded&&!loadError&&!runs.length&&<EmptyState title="No runs yet"/>}
  </div>
  {run&&<aside className="section run-detail"><div className="section-heading"><h2>{run.title}</h2><button className="icon-button" onClick={close} aria-label="Close run details"><X/></button></div><div className="button-row"><StatusBadge status={run.status}/>{run.origin==='demo'&&<DemoBadge/>}</div><p>{run.summary}</p><small className="meta">{[`Started ${date(run.started_at)}`,run.elapsed_seconds!==null&&duration(run.elapsed_seconds),run.triggered_by==='schedule'?'Schedule':'Manual run'].filter(Boolean).join(' · ')}</small>
  <div className="button-row"><WorkflowLink {...workflowRef(run)} label="Open workflow" openWorkflow={openWorkflow}/></div>
  {active(run.status)&&<button className="danger full" onClick={()=>confirmStop(run.id)}><Square size={16}/>Stop run</button>}
  {run.pending_action&&run.status==='awaiting_approval'&&<section className="approval"><h3>Review this change</h3><p>{String(run.pending_action.arguments.reason||'The agent proposes this desktop change.')}</p><dl>{Object.entries(run.pending_action.arguments).filter(([k])=>['window_title','value','label','action'].includes(k)).map(([k,v])=><div key={k}><dt>{human(k)}</dt><dd>{text(v)}</dd></div>)}</dl><div className="button-row"><button className="secondary" disabled={busy} onClick={()=>decide(false)}>Decline</button><button className="primary" disabled={busy} onClick={()=>decide(true)}>Approve change</button></div></section>}
  {['failed','blocked','interrupted'].includes(run.status)&&<p className="notice">Check the activity, then update the workflow before retrying.</p>}
  <details><summary>Technical details</summary>
    {run.pending_action&&run.status==='awaiting_approval'&&<pre>{JSON.stringify(run.pending_action,null,2)}</pre>}
    {!!run.events?.length&&<ol className="timeline">{run.events.map(e=><li key={e.id}><strong>{e.title}</strong><time>{date(e.timestamp)}</time>{e.detail!==null&&<pre>{text(e.detail)}</pre>}</li>)}</ol>}
  </details>
  <RunReport key={run.id} run={run} feedback={feedback} busy={busy}/></aside>}</div></>
}
