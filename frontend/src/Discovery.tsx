import { useEffect, useState } from 'react'
import { ArrowRight, X } from 'lucide-react'
import { api } from './api'
import type { Task, Workflow, SavedWorkflow } from './types'
import type { WorkflowRef } from './routes'
import { date, EmptyState, EvidenceList, Section } from './components'

type Pattern = {
  id:string;title:string;summary:string;goal:string;occurrence_count:number;confidence:number;
  confidence_label:'high'|'medium'|'low';explanation:string;first_seen:string;last_seen:string;apps:string[];
  status:string;coverage_notes:string;typical_time_of_day:string;timezone:string;
  approximate_duration_seconds:number|null;duration_sample_count:number;
  occurrences?:Task[];draft?:Draft|null;workflow_id?:string|null
}
type Draft = {title:string;reconstruction:Workflow;variable_inputs:{name:string;description:string;observed_values:string[];evidence:Task['evidence']}[];comparison_notes:string}
type Scan = {status:string;enabled:boolean;interval_minutes:number;error?:string;coverage_notes?:string;catching_up?:boolean;end_time?:string;finished_at?:string}

export function Discovery({tab,query,refresh,openWorkflow}:{tab:string;query:string;refresh:()=>void;openWorkflow:(ref:WorkflowRef)=>void}) {
  const [patterns,setPatterns]=useState<Pattern[]>([])
  const [scan,setScan]=useState<Scan|null>(null)
  const [sort,setSort]=useState('frequent')
  const [dismissed,setDismissed]=useState(false)
  const [detail,setDetail]=useState<Pattern|null>(null)
  const [draft,setDraft]=useState<Draft|null>(null)
  const [title,setTitle]=useState('')
  const [busy,setBusy]=useState('')
  const [error,setError]=useState('')
  const [loaded,setLoaded]=useState(false)
  async function load() {
    const [items,state]=await Promise.all([api<Pattern[]>(`/discovery/patterns?sort=${sort}&include_dismissed=${dismissed}`),api<Scan>('/discovery/status')])
    setPatterns(items);setScan(state);setLoaded(true)
  }
  useEffect(()=>{let alive=true;const poll=()=>{if(alive)void load().catch(e=>{if(alive)setError(e.message)})};poll();const t=setInterval(poll,5000);return()=>{alive=false;clearInterval(t)}},[sort,dismissed])
  async function act(label:string,fn:()=>Promise<void>) {if(busy)return;setBusy(label);setError('');try{await fn();await load()}catch(e){setError((e as Error).message)}finally{setBusy('')}}
  async function review(p:Pattern) {await act('review',async()=>{const item=await api<Pattern>(`/discovery/patterns/${p.id}`);setDetail(item);setDraft(item.draft||null);setTitle(item.draft?.title||item.title)})}
  const matching=patterns.filter(p=>`${p.title} ${p.summary} ${p.apps.join(' ')}`.toLowerCase().includes(query.toLowerCase()))
  const running=scan?.status==='queued'||scan?.status==='running'
  function cards(items:Pattern[]) {return items.length?<div className="grid three">{items.map(p=><article className="workflow-card discovery-card" key={p.id}>
    <div className="discovery-card-heading"><h3>{p.title}</h3><span className="badge">{p.occurrence_count}×</span></div>
    <p>{p.summary}</p><div className="tags">{p.apps.map(app=><span key={app}>{app}</span>)}<span>{p.confidence_label==='high'?'Strong match':'Possible match'} · {Math.round(p.confidence*100)}%</span></div>
    <small className="meta">Last seen {date(p.last_seen)}{p.approximate_duration_seconds!==null?` · ~${Math.max(1,Math.round(p.approximate_duration_seconds/60))} min`:''}</small>
    <div className="button-row"><button className="secondary" disabled={!!busy} onClick={()=>void review(p)}>Review</button><button className="primary" disabled={!!busy||p.status==='dismissed'} onClick={()=>void act('compare',async()=>{setDetail(await api<Pattern>(`/discovery/patterns/${p.id}`));const d=await api<Draft>(`/discovery/patterns/${p.id}/create-workflow`,{});setDraft(d);setTitle(d.title)})}>Turn into workflow <ArrowRight size={14}/></button></div>
    <button className="link-button" disabled={!!busy} onClick={()=>void act('decision',async()=>{await api(`/discovery/patterns/${p.id}/${p.status==='dismissed'?'accept':'dismiss'}`,{});if(detail?.id===p.id)setDetail(null)})}>{p.status==='dismissed'?'Restore suggestion':p.status==='saved_as_workflow'?'Hide suggestion':'Dismiss'}</button>
    {p.status==='accepted'&&<small>Accepted · draft still needs review and saving</small>}{p.status==='saved_as_workflow'&&<small>Saved to your workflow library</small>}
  </article>)}</div>:<EmptyState title={loaded?'No supported repeated tasks yet':'Loading suggestions…'}>Suggestions appear after at least two distinct original occurrences. Scans may cover only part of your history; this does not mean no activity was recorded.</EmptyState>}
  return <>
    {busy==='compare'&&<p role="status" className="discovery-notice">Comparing original occurrences and building a draft… This can take a minute.</p>}
    <div className="discovery-controls"><label>Sort by <select aria-label="Sort repeated tasks" value={sort} onChange={e=>setSort(e.target.value)}><option value="frequent">Most frequent</option><option value="recent">Recently repeated</option><option value="confidence">Highest confidence</option></select></label><label><input type="checkbox" checked={dismissed} onChange={e=>setDismissed(e.target.checked)}/> Show dismissed</label></div>
    {tab!=='Most repeated'&&<><Section title="Suggested workflows">{cards(matching.filter(p=>p.confidence_label==='high'))}</Section>{matching.some(p=>p.confidence_label==='medium')&&<Section title="Possible repeated tasks">{cards(matching.filter(p=>p.confidence_label==='medium'))}</Section>}</>}
    {tab==='Most repeated'&&<Section title="Most repeated tasks">{cards(matching)}</Section>}
    {scan?.coverage_notes&&<details className="section discovery-coverage"><summary>What this check covered</summary><p>{scan.coverage_notes}</p>{scan.end_time&&<small>History inspected through {date(scan.end_time)}</small>}</details>}
    {detail&&<section className="section discovery-review" aria-label="Review discovered pattern"><div className="discovery-card-heading"><h2>{detail.title}</h2><button className="icon-button" aria-label="Close pattern review" onClick={()=>{setDetail(null);setDraft(null)}}><X size={18}/></button></div><p>{detail.explanation}</p><p>{detail.occurrence_count} distinct occurrences · {date(detail.first_seen)} — {date(detail.last_seen)}</p><p className="muted">Usually around {detail.typical_time_of_day} ({detail.timezone}). {detail.approximate_duration_seconds===null?'Duration is unknown.':`Median observed span: ${Math.round(detail.approximate_duration_seconds/60)} min from ${detail.duration_sample_count} occurrences. This is elapsed span, not active effort.`}</p>
      <details><summary>Review each original occurrence</summary>{detail.occurrences?.map(t=><article key={t.id} className="discovery-occurrence"><strong>{t.title}</strong><time>{date(t.timestamp)}</time><p>{t.summary}</p><EvidenceList evidence={t.evidence} expanded/></article>)}</details><p className="footnote">{detail.coverage_notes}</p>
      <div className="button-row"><button className="secondary" disabled={!!busy} onClick={()=>void act('accept',async()=>setDetail(await api<Pattern>(`/discovery/patterns/${detail.id}/accept`,{})))}>Accept suggestion</button><button className="primary" disabled={!!busy} onClick={()=>void act('compare',async()=>{const d=await api<Draft>(`/discovery/patterns/${detail.id}/create-workflow`,{});setDraft(d);setTitle(d.title)})}>Compare & create draft</button></div>
      {draft&&<div className="discovery-draft"><h3>Review reusable workflow draft</h3><p>{draft.comparison_notes}</p><label className="field"><span>Workflow title</span><input value={title} maxLength={300} onChange={e=>setTitle(e.target.value)}/></label><h4>Shared observed steps</h4><ol>{draft.reconstruction.steps.map((s,i)=><li key={i}>{s.description}<EvidenceList evidence={s.evidence}/></li>)}</ol><h4>Inputs that change</h4>{draft.variable_inputs.length?draft.variable_inputs.map(v=><div key={v.name}><strong>{v.name}</strong><p>{v.description}</p><details><summary>Values observed in history</summary><ul>{v.observed_values.map((value,i)=><li key={i}>{value}</li>)}</ul><EvidenceList evidence={v.evidence}/></details></div>):<p>No changing values were recovered.</p>}<h4>Details needed for a future run</h4>{draft.reconstruction.missing_values.length?<ul>{draft.reconstruction.missing_values.map(v=><li key={v}>{v}</li>)}</ul>:<p>No missing details reported in the inspected evidence.</p>}<button className="primary" disabled={!!busy||!title.trim()} onClick={()=>void act('save',async()=>{const saved=await api<SavedWorkflow>(`/discovery/patterns/${detail.id}/save-workflow`,{title:title.trim()});refresh();openWorkflow({workflowId:saved.id})})}>{busy==='save'?'Saving…':'Save workflow for review'}</button></div>}
    </section>}
  </>
}
