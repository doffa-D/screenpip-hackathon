import { useEffect, useState } from 'react'
import { api } from './api'
import type { Run, RunReport as Report } from './types'
import { active, date, human, text } from './components'

export function RunReport({run,feedback,busy}:{run:Run;feedback:(verdict:'looks_good'|'something_wrong',notes:string)=>void;busy:boolean}) {
  const [report,setReport]=useState<Report|null>(null)
  const [error,setError]=useState('')
  const [notes,setNotes]=useState('')
  useEffect(()=>{
    let alive=true;setReport(run.report||null);setError('');setNotes(run.feedback?.notes||'')
    if(!active(run.status)&&run.origin!=='demo'&&!run.report)api<Report>(`/runs/${run.id}/report`).then(r=>{if(alive)setReport(r)}).catch(e=>{if(alive)setError(e.message)})
    return()=>{alive=false}
  },[run.id,run.status,run.report,run.feedback?.reviewed_at])
  if(active(run.status)||run.origin==='demo')return null
  return <details aria-label="Final execution report"><summary>Report</summary>
    {error&&<p role="alert">{error}</p>}
    {report?<>
      {!!report.workflow_revision&&<small className="meta">Revision {report.workflow_revision}</small>}
      <p>{report.actions_attempted.length} actions attempted · {report.actions_completed.length} returned successfully · {report.verification_results.length} live checks</p>
      <h4>Values used</h4>{report.values_used?<dl>{Object.entries(report.values_used).map(([k,v])=><div key={k}><dt>{human(k)}</dt><dd className="workflow-preserve-text">{text(v)}</dd></div>)}</dl>:<p>Not captured.</p>}
      {report.instructions&&<details><summary>Execution instructions</summary><p>{report.instructions}</p></details>}
      <h4>Actions attempted</h4>{report.actions_attempted.length?<ol>{report.actions_attempted.map(a=><li key={a.event_id}>{human(String(a.arguments.action||'Change'))}: {String(a.arguments.label||'Selected control')}<details><summary>Exact action</summary><pre>{text(a.arguments)}</pre></details></li>)}</ol>:<p>No actions recorded.</p>}
      <h4>Live verification</h4>{report.verification_results.length?report.verification_results.map(c=><details key={c.event_id}><summary>{(c.result as {verified?:boolean})?.verified?'Passed':'Did not pass'}</summary><pre>{text(c.result)}</pre></details>):<p>Not verified.</p>}
      {!!report.errors.length&&<><h4>Errors and interruptions</h4>{report.errors.map(e=><details key={e.event_id}><summary>{e.message}</summary><pre>{text(e.detail)}</pre></details>)}</>}
      <details><summary>What this report can verify</summary><ul>{report.limitations.map(l=><li key={l}>{l}</li>)}</ul></details>
    </>:<p>Loading report…</p>}
    <h3>Did it work?</h3>
    {run.feedback&&<p role="status">Saved: {run.feedback.verdict==='looks_good'?'Everything looks good':'Something went wrong'} · {date(run.feedback.reviewed_at)}</p>}
    <label className="field"><span>Review notes (optional)</span><textarea rows={2} maxLength={4000} value={notes} onChange={e=>setNotes(e.target.value)}/></label>
    <div className="button-row"><button className="secondary" disabled={busy||!report} onClick={()=>feedback('looks_good',notes)}>Everything looks good</button><button className="secondary" disabled={busy||!report} onClick={()=>feedback('something_wrong',notes)}>Something went wrong</button></div>
  </details>
}
