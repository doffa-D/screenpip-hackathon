import { RuntimeStatus } from './RuntimeStatus'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { BookmarkPlus, Circle, Square } from 'lucide-react'
import { api } from './api'
import type { Health, SavedWorkflow, Schedule } from './types'
import { href } from './routes'
import type { WorkflowRef } from './routes'
import { cap, date, DemoBadge, EmptyState, LoadingState, PageHeader, PrivacyNote, ScheduleRow, Section, StatusBadge, TaskRow, Toggle } from './components'

type Segment = {id:string; title:string; started_at:string; ended_at:string|null; status:string; markers:{timestamp:string;label:string}[]; task_id:string|null; job_id:string|null;capture_status:string;step_count:number|null;summary:string|null}
export function RecordPage({openWorkflow,notify}: {go?:(p:string)=>void;openWorkflow:(ref:WorkflowRef)=>void;notify:(s:string)=>void}) {
  const [records,setRecords]=useState<Segment[]>([]); const [loaded,setLoaded]=useState(false); const [loadError,setLoadError]=useState(''); const pendingReview=useRef<string|null>(null); const [busy,setBusy]=useState(false); const [clock,setClock]=useState(Date.now()); const openRef=useRef(openWorkflow); openRef.current=openWorkflow
  async function load(){try {const rows=await api<Segment[]>('/recordings');setRecords(rows);setLoadError('');const ready=rows.find(r=>r.id===pendingReview.current&&r.status==='ready'&&r.task_id);if(ready){pendingReview.current=null;openRef.current({taskId:ready.task_id})}} catch(e){setLoadError((e as Error).message)}finally{setLoaded(true)}}
  useEffect(()=>{void load();const timer=setInterval(()=>{setClock(Date.now());void load()},2000);return()=>clearInterval(timer)},[])
  const current=records.find(r=>r.status==='recording')
  async function act(path:string,body:unknown={}){setBusy(true);try{const record=await api<Segment>(path,body);if(path.endsWith('/stop'))pendingReview.current=record.id;await load()}catch(e){notify((e as Error).message)}finally{setBusy(false)}}
  return <>
  <PageHeader title="Record"/>
  {!loaded&&<LoadingState title="Loading recordings"/>}{loadError&&<p className="notice" role="alert">{loadError}</p>}
  <section className="section"><div className="record-center">
    <div className={`record-orb ${current?'pulsing':''}`} aria-hidden="true"><i/></div>
    <h2>{current?'Recording your workflow':'Ready to record'}</h2>
    {current&&<p className="meta">{`${Math.floor(Math.max(0,clock-+new Date(current.started_at))/60000)}:${String(Math.floor(Math.max(0,clock-+new Date(current.started_at))/1000)%60).padStart(2,'0')}`} · Started {date(current.started_at)}</p>}
    <p className="meta">Start before your task. Stop when you finish. Screenpipe keeps recording normally.</p>
    <div className="button-row record-controls" aria-label="Recording controls">
      <button type="button" className="primary" disabled={!loaded||!!loadError||busy||!!current} onClick={()=>void act('/recordings/start',{title:'Recorded workflow'})}><Circle size={16}/> Start recording</button>
      <button type="button" className="danger" disabled={busy||!current} onClick={()=>current&&void act(`/recordings/${current.id}/stop`)}><Square size={16}/> Stop recording</button>
      <button type="button" className="secondary" disabled={busy||!current} onClick={()=>current&&void act(`/recordings/${current.id}/markers`,{label:'Step bookmark'})}><BookmarkPlus size={16}/> Mark step</button>
    </div>
    {current&&<p className="meta" role="status">{current.markers.length} {current.markers.length===1?'step marked':'steps marked'}</p>}
  </div></section>
  <Section title="Tips"><ul className="tips-list"><li>Start right before the task you want to capture.</li><li>Mark important moments with Ctrl + Shift + M.</li></ul></Section>
  <Section title="Recorded segments"><div className="item-list">{records.map(r=><TaskRow key={r.id} task={{id:r.id,title:r.title}} taskId={r.task_id} meta={date(r.started_at)} badge={<StatusBadge status={r.status}/>} openWorkflow={openWorkflow}/>)}</div></Section></>
}

type Occurrence = {id:string;status:string;explanation:string;scheduled_at:string;run_id?:string|null}
export function SchedulePage({notify,initialWorkflowId='',editId,library,go,openWorkflow}: {notify:(s:string)=>void;initialWorkflowId?:string;editId?:string;library:SavedWorkflow[];go:(p:string)=>void;openWorkflow:(ref:WorkflowRef)=>void}) {
  const [items,setItems]=useState<Schedule[]>([]);const [loaded,setLoaded]=useState(false);const [loadError,setLoadError]=useState('');const [editing,setEditing]=useState('');const [history,setHistory]=useState<{id:string;items:Occurrence[]}|null>(null);const [confirmDelete,setConfirmDelete]=useState('');const openedEdit=useRef('')
  const [form,setForm]=useState({workflow_id:initialWorkflowId,frequency:'once',local_date:new Date().toLocaleDateString('en-CA'),local_time:'18:00',timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,enabled:true,notifications:true}); const [preview,setPreview]=useState<string|null>(null); const [busy,setBusy]=useState(false)
  const titles=new Map(library.map(w=>[w.id,w.title]))
  async function load(){try{setItems(await api<Schedule[]>('/schedules'));setLoadError('')}catch(e){setLoadError((e as Error).message)}finally{setLoaded(true)}}
  useEffect(()=>{void load();const timer=setInterval(()=>void load(),5000);return()=>clearInterval(timer)},[])
  useEffect(()=>{let alive=true;setPreview(null);if(form.workflow_id)api<{next_run_at:string|null}>('/schedules/preview',form).then(v=>{if(alive)setPreview(v.next_run_at)}).catch(()=>{});return()=>{alive=false}},[form])
  function edit(s:Schedule){setEditing(s.id);setForm({workflow_id:s.workflow_id,frequency:s.frequency,local_date:s.local_date,local_time:s.local_time,timezone:s.timezone,enabled:s.enabled,notifications:s.notifications??true})}
  async function save(){setBusy(true);try{await api(editing?`/schedules/${editing}`:'/schedules',form,editing?'PATCH':'POST');setEditing('');await load();notify('Schedule saved')}catch(e){notify((e as Error).message)}finally{setBusy(false)}}
  useEffect(()=>{setEditing('');setForm(previous=>({...previous,workflow_id:initialWorkflowId}))},[initialWorkflowId])
  useEffect(()=>{const s=editId&&openedEdit.current!==editId?items.find(i=>i.id===editId):undefined;if(s){openedEdit.current=s.id;edit(s)}},[editId,items])
  async function toggle(s:Schedule){try{const {workflow_id,frequency,local_date,local_time,timezone,notifications}=s;await api(`/schedules/${s.id}`,{workflow_id,frequency,local_date,local_time,timezone,notifications,enabled:!s.enabled},'PATCH');await load()}catch(e){notify((e as Error).message)}}
  async function remove(id:string){try{await api(`/schedules/${id}`,{},'DELETE');setConfirmDelete('');await load()}catch(e){notify((e as Error).message)}}
  return <>
  <PageHeader title="Schedule" action={<button className="secondary" onClick={()=>{setEditing('');setForm(f=>({...f,workflow_id:''}))}}>New</button>}/>
  {!loaded&&<LoadingState title="Loading schedules"/>}{loadError&&<p className="notice" role="alert">{loadError}</p>}
  <div className="split-layout schedule-layout"><Section title="Upcoming">{items.length?<div className="item-list">{items.slice().sort((a,b)=>(a.next_run_at||'z').localeCompare(b.next_run_at||'z')).map(s=><div key={s.id}><ScheduleRow s={s} title={titles.get(s.workflow_id)??s.title} openWorkflow={openWorkflow} trailing={<Toggle label={`Enable ${titles.get(s.workflow_id)??s.title}`} checked={s.enabled} onChange={()=>void toggle(s)}/>}/><div className="button-row"><button className="secondary" onClick={()=>edit(s)}>Edit</button><button className="secondary" onClick={()=>history?.id===s.id?setHistory(null):api<Occurrence[]>(`/schedules/${s.id}/occurrences`).then(o=>setHistory({id:s.id,items:o})).catch(e=>notify(e.message))}>History</button>{confirmDelete===s.id?<><button className="danger" onClick={()=>void remove(s.id)}>Confirm delete</button><button className="link-button" onClick={()=>setConfirmDelete('')}>Cancel</button></>:<button className="danger" onClick={()=>setConfirmDelete(s.id)}>Delete</button>}</div>{history?.id===s.id&&<div className="item-list" aria-label="History">{history.items.length?history.items.map(o=><div className="setting-row" key={o.id}><div><span>{date(o.scheduled_at)}</span>{o.explanation&&<small className="meta">{o.explanation}</small>}</div>{o.run_id?<a href={`#/${href.run(o.run_id)}`}><StatusBadge status={o.status}/></a>:<StatusBadge status={o.status}/>}</div>):<small className="meta">No history yet.</small>}</div>}</div>)}</div>:<EmptyState title="No schedules yet." action={<button className="secondary" onClick={()=>go(href.workflows())}>Go to workflows</button>}/>}</Section>
  <Section title={editing?'Edit schedule':'New schedule'} badge={items.find(s=>s.id===editing)?.origin==='demo'?<DemoBadge/>:undefined}>
    <label className="field"><span>Workflow</span><select value={form.workflow_id} onChange={e=>setForm({...form,workflow_id:e.target.value})}><option value="">Choose a saved workflow</option>{library.map(w=><option key={w.id} value={w.id}>{w.title}</option>)}</select></label>
    <label className="field"><span>When to run</span><select value={form.frequency} onChange={e=>setForm({...form,frequency:e.target.value})}>{['once','daily','weekly','monthly'].map(s=><option key={s} value={s}>{cap(s)}</option>)}</select></label>
    <div className="grid two"><label className="field"><span>Start date</span><input type="date" value={form.local_date} onChange={e=>setForm({...form,local_date:e.target.value})}/></label><label className="field"><span>Local time</span><input type="time" value={form.local_time} onChange={e=>setForm({...form,local_time:e.target.value})}/></label></div>
    <label className="field" title="Monthly dates use the last available day. Nonexistent spring times are skipped; repeated autumn times run once. Missed runs are recorded without catch-up."><span>Timezone</span><input value={form.timezone} onChange={e=>setForm({...form,timezone:e.target.value})}/></label>
    <div className="setting-row"><span>Notify me</span><Toggle checked={form.notifications} label="Schedule run notifications" onChange={v=>setForm({...form,notifications:v})}/></div>
    <p className="notice">{preview?`Next run: ${date(preview)}`:!form.workflow_id?'Choose a workflow to preview its next run.':'Choose a future date and valid timezone.'}</p>
    <button className="primary full" disabled={busy||!preview||!form.workflow_id} onClick={save}>Save schedule</button>{editing&&<button className="link-button" onClick={()=>setEditing('')}>Cancel editing</button>}
  </Section></div></>
}

type Prefs={theme:string;accent:string;desktop_enabled:boolean;notifications:boolean;provider:string;model:string;endpoint:string}
export function SettingsPage({health,refresh,notify}: {health:Health|null;refresh:()=>void;notify:(s:string)=>void}) {
  const [prefs,setPrefs]=useState<Prefs|null>(null);const [disk,setDisk]=useState<{free_bytes:number;data_directory:string}|null>(null);const [checks,setChecks]=useState<Record<string,{status:string;elapsed_seconds?:number;explanation:string;details?:unknown}>>({});const [busy,setBusy]=useState('');const [key,setKey]=useState('');const [shortcuts,setShortcuts]=useState<Record<string,string>>({})
  useEffect(()=>{api<Record<string,string>>('/shortcuts').then(setShortcuts).catch(()=>{});Promise.all([api<Prefs>('/settings'),api<typeof disk>('/system/status'),api<typeof checks>('/capabilities')]).then(([p,d,c])=>{setPrefs(p);setDisk(d);setChecks(c)}).catch(e=>notify(e.message))},[])
  async function change(next:Prefs){try{if(next.notifications&&!prefs?.notifications&&'Notification'in window)await Notification.requestPermission();const {theme,accent,desktop_enabled,notifications}=next;setPrefs(await api<Prefs>('/settings',{theme,accent,desktop_enabled,notifications},'PATCH'));window.dispatchEvent(new Event('melon-preferences'));refresh()}catch(e){notify((e as Error).message)}}
  async function test(name:string){setBusy(name);try{const value=await api<typeof checks[string]>(`/connections/${name}/test`,{});setChecks(c=>({...c,[name]:value}));notify(`${name}: ${value.status}${value.elapsed_seconds?` in ${value.elapsed_seconds}s`:''}`)}catch(e){notify((e as Error).message)}finally{setBusy('')}}
  const select=(label:string,value:string,options:string[],onChange:(v:string)=>void)=><label className="field"><span>{label}</span><select value={value} onChange={e=>onChange(e.target.value)}>{options.map(s=><option key={s} value={s}>{cap(s)}</option>)}</select></label>
  const connection=(name:string,title:string,extra?:ReactNode)=><div className="connection-block" key={name}><div className="setting-row"><h3>{title}</h3><StatusBadge status={checks[name]?.status||'unchecked'}/></div>{extra}{checks[name]?.explanation&&<small className="meta">{checks[name].explanation}</small>}<div className="button-row"><button className="secondary" disabled={!!busy} onClick={()=>test(name)}>{busy===name?'Testing…':'Test'}</button>{checks[name]?.elapsed_seconds!==undefined&&<small className="meta">{checks[name].elapsed_seconds}s</small>}</div>{checks[name]?.details!==undefined&&<details><summary>Details</summary><pre>{JSON.stringify(checks[name].details,null,2)}</pre></details>}</div>
  return <><PageHeader title="Settings"/>
  <Section title="Connections"><div className="grid three">
  {connection('model','Model',prefs&&<><div className="provider-summary"><span>{prefs.provider==='azure'?'Azure OpenAI':'OpenAI'}</span><strong>{prefs.model}</strong></div><details className="provider-editor"><summary>Edit provider</summary>{select('Provider',prefs.provider,['azure','openai'],v=>setPrefs({...prefs,provider:v}))}<label className="field"><span>Endpoint</span><input value={prefs.endpoint} onChange={e=>setPrefs({...prefs,endpoint:e.target.value})}/></label><label className="field"><span>Model / deployment</span><input value={prefs.model} onChange={e=>setPrefs({...prefs,model:e.target.value})}/></label><label className="field"><span>Replacement API key (blank keeps current)</span><input type="password" autoComplete="off" value={key} onChange={e=>setKey(e.target.value)}/></label><button className="secondary" onClick={async()=>{try{setPrefs(await api<Prefs>('/settings/provider',{provider:prefs.provider,endpoint:prefs.endpoint,model:prefs.model,...(key?{api_key:key}:{})},'PATCH'));setKey('');notify('Provider saved')}catch(e){notify((e as Error).message)}}}>Save provider</button></details></>)}
  {connection('desktop','Desktop',prefs&&<div className="setting-row"><span>Allow desktop control</span><Toggle checked={prefs.desktop_enabled} label="Allow desktop control" onChange={v=>void change({...prefs,desktop_enabled:v})}/></div>)}
  {connection('screenpipe','Screenpipe')}</div>
  <small className="meta">{health?'Local server connected':'Local server unavailable'} · {disk?`${(disk.free_bytes/1024**3).toFixed(1)} GB free · ${disk.data_directory}`:'Checking storage…'}</small></Section>
  {prefs&&<Section title="Appearance"><div className="grid three">{select('Theme',prefs.theme,['light','dark','system'],v=>void change({...prefs,theme:v}))}{select('Accent',prefs.accent,['indigo','pink','green'],v=>void change({...prefs,accent:v}))}<div className="setting-row"><span>Run notifications</span><Toggle checked={prefs.notifications} label="Run notifications" onChange={v=>void change({...prefs,notifications:v})}/></div></div></Section>}<RuntimeStatus/><Section title="Shortcuts">{Object.entries(shortcuts).map(([key,value])=><div className="setting-row" key={key}><kbd>{key}</kbd><small>{value}</small></div>)}</Section><PrivacyNote/></>
}
