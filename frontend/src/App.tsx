import { workflowPlan } from './workflow-plan'
import { Chat } from './Chat'
import { useEffect, useRef, useState } from 'react'
import { ArrowRight, MoonStar, Play, Sparkles, X } from 'lucide-react'
import { api, ApiError } from './api'
import type { Health, NightReport, Run, Task, SavedWorkflow, Schedule, Workflow } from './types'
import { active, EmptyState, LoadingState, PageHeader, RunRow, ScheduleRow, Section, Sidebar, TaskRow, text, WorkflowRow } from './components'
import type { Page } from './components'
import { href, legacyRedirect, parseRoute } from './routes'
import type { WorkflowRef } from './routes'
import { Memories } from './Memories'
import { Workflows } from './Workflows'
import { WorkflowPage } from './WorkflowPage'
import { WorkflowActivity } from './WorkflowActivity'
import { RecordPage, SchedulePage } from './support-pages'
import { NightShift } from './NightShift'

const readHash = () => window.location.hash
const sameJson = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const entries = (o: Record<string, string>) => Object.entries(o).sort()
const upsertById = (list: SavedWorkflow[], w: SavedWorkflow) => list.some(x => x.id === w.id) ? list.map(x => x.id === w.id ? w : x) : [w, ...list]

type HomeProps = { loaded: boolean; library: SavedWorkflow[]; saved: Task[]; runs: Run[]; schedules: Schedule[]; night: NightReport | null; go: (p: string) => void; openWorkflow: (ref: WorkflowRef) => void; openRun: (id: string) => void }
function Home({ loaded, library, saved, runs, schedules, night, go, openWorkflow, openRun }: HomeProps) {
  const recent = [...library].sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at)).slice(0, 3)
  const tasks = recent.length ? [] : saved.slice(0, 3)
  const lastRun = runs.find(r => active(r.status)) ?? runs[0]
  const next = schedules.filter(s => s.enabled && s.next_run_at).sort((a, b) => a.next_run_at!.localeCompare(b.next_run_at!))[0]
  const titles = new Map(library.map(w => [w.id, w.title]))
  const viewAll = (to: string) => <button className="link-button" onClick={() => go(to)}>View all <ArrowRight size={16}/></button>
  return <>
    <PageHeader title="Home"/>
    {night && night.items.length > 0 && <Section title="Overnight report" subtitle={night.headline} action={<button className="primary" onClick={() => go(href.nightshift())}><MoonStar size={16}/> Review report</button>}/>}
    {!loaded ? <LoadingState title="Loading"/> : !recent.length && !tasks.length && !lastRun && !next ?
      <EmptyState title="No recent work yet." action={<button className="secondary" onClick={() => go(href.memories())}>Find a memory <ArrowRight size={16}/></button>}/> : <>
      {(recent.length > 0 || tasks.length > 0) && <Section title="Recent workflows" action={viewAll(recent.length ? href.workflows() : href.memories())}><div className="item-list">
        {recent.map(w => <WorkflowRow key={w.id} w={w} onOpen={() => openWorkflow({ workflowId: w.id })}/>)}
        {tasks.map(t => <TaskRow key={t.id} task={t} openWorkflow={openWorkflow}/>)}
      </div></Section>}
      {lastRun && <Section title={active(lastRun.status) ? 'Active run' : 'Last run'} action={viewAll(href.workflows())}><div className="item-list"><RunRow run={lastRun} openRun={openRun}/></div></Section>}
      {next && <Section title="Next schedule" action={viewAll(href.schedule())}><div className="item-list"><ScheduleRow s={next} title={titles.get(next.workflow_id)} openWorkflow={openWorkflow}/></div></Section>}
    </>}
  </>
}

export default function App() {
  const [path, setPath] = useState(readHash)
  const route = parseRoute(path)
  const [health, setHealth] = useState<Health | null>(null)
  const [saved, setSaved] = useState<Task[]>([])
  const [memoriesLoaded, setMemoriesLoaded] = useState(false)
  const [memoryError, setMemoryError] = useState('')
  const [runs, setRuns] = useState<Run[]>([])
  const [run, setRun] = useState<Run | null>(null)
  const [message, setMessage] = useState('')
  const [results, setResults] = useState<Task[] | null>(null)
  // Transient workflow page state. It is hydrated for exactly one route id (hydratedId) and cleared when the user leaves the workflow route.
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [draftTask, setDraftTask] = useState<Task | null>(null)
  const [fetchedSaved, setFetchedSaved] = useState<SavedWorkflow | null>(null)
  const [hydratedId, setHydratedId] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [missing, setMissing] = useState<Record<string, string>>({})
  const [instructions, setInstructions] = useState('')
  const [autoApprove, setAutoApprove] = useState(false)
  const [busy, setBusy] = useState('')
  const [seconds, setSeconds] = useState(0)
  const [searchTime, setSearchTime] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [library, setLibrary] = useState<SavedWorkflow[]>([])
  const [libraryLoaded,setLibraryLoaded]=useState(false)
  const [libraryError,setLibraryError]=useState('')
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [schedulesLoaded, setSchedulesLoaded] = useState(false)
  const [night, setNight] = useState<NightReport | null>(null)
  const version = useRef(0)
  const resolving = useRef('')
  const routeRef = useRef(route); routeRef.current = route
  const libraryRef = useRef(library); libraryRef.current = library
  const page: Page = route.page === 'workflow' ? 'workflows' : route.page
  const workflowId = route.page === 'workflow' ? route.id : null
  const go = (p: string, replace = false) => { if (replace) window.location.replace(`#/${p}`); else window.location.hash = `/${p}` }
  async function refresh() {
    const [w, h, t, r, s, n] = await Promise.allSettled([api<SavedWorkflow[]>('/workflows'), api<Health>('/health'), api<Task[]>('/memories?limit=500'), api<Run[]>('/runs'), api<Schedule[]>('/schedules'), api<NightReport>('/nightshift/report')])
    setLibraryLoaded(true)
    if(w.status==='fulfilled'){setLibrary(w.value);setLibraryError('')}else setLibraryError(w.reason.message)
    setHealth(h.status === 'fulfilled' ? h.value : null)
    if (t.status === 'fulfilled') {setSaved(t.value);setMemoriesLoaded(true);setMemoryError('')} else {setMemoryError(t.reason.message);setMemoriesLoaded(true)}
    // Track the active run for notifications, but never swap the run a runs/<id> route is showing.
    if (r.status === 'fulfilled') { setRuns(r.value); const current = r.value.find(x => active(x.status)); const shown = routeRef.current; if (current && !(shown.page === 'runs' && shown.id)) setRun(prev => prev && active(prev.status) ? prev : current) }
    if (s.status === 'fulfilled') { setSchedules(s.value); setSchedulesLoaded(true) }
    setNight(n.status === 'fulfilled' ? n.value : null)
  }
  useEffect(() => {
    const apply = async () => {try { const p = await api<{theme:string;accent:string}>('/settings'); document.documentElement.dataset.theme=p.theme; document.documentElement.dataset.accent=p.accent } catch {} }
    void apply(); window.addEventListener('melon-preferences',apply); return()=>window.removeEventListener('melon-preferences',apply)
  },[])
  useEffect(()=>{ if(run?.status!=='awaiting_approval'&& !['completed','failed','blocked','cancelled','interrupted'].includes(run?.status||''))return; api<{notifications:boolean}>('/settings').then(p=>{if(p.notifications&&run?.notify!==false){setToast(`${run?.title}: ${run?.status.replaceAll('_',' ')}`);if('Notification'in window&&Notification.permission==='granted')new Notification('Melon',{body:`${run?.title}: ${run?.status.replaceAll('_',' ')}`,icon:'/melon-logo.png'})}}).catch(()=>{}) },[run?.id,run?.status])
  useEffect(() => { const onHash = () => setPath(readHash()); window.addEventListener('hashchange', onHash); void refresh(); const timer = setInterval(() => void refresh(), 15000); return () => { clearInterval(timer); window.removeEventListener('hashchange', onHash) } }, [])
  useEffect(() => { if (!busy) return; setSeconds(0); const t = setInterval(() => setSeconds(v => v + 1), 1000); return () => clearInterval(t) }, [busy])
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(''), 5500); return () => clearTimeout(t) }, [toast])
  useEffect(() => {
    if (!run || !active(run.status)) return
    let stopped = false; let timer: ReturnType<typeof setTimeout>
    const poll = async () => { try { const next = await api<Run>(`/runs/${run.id}`); if (!stopped) { setRun(next); if (!active(next.status)) void refresh() } } catch (e) { if (!stopped) setError((e as Error).message) } if (!stopped) timer = setTimeout(poll, 1000) }
    timer = setTimeout(poll, 500); return () => { stopped = true; clearTimeout(timer) }
  }, [run?.id, run?.status])

  function clearDraft() { setWorkflow(null); setDraftTask(null); setFetchedSaved(null); setHydratedId(null); setUnavailable(null); setValues({}); setMissing({}); setInstructions('') }
  function upsert(w: SavedWorkflow) { setLibrary(list => upsertById(list, w)); setFetchedSaved(w) }
  function hydrate(w: SavedWorkflow) {
    setValues({...Object.fromEntries(Object.entries(w.reconstruction.historical_values).map(([k,v])=>[k,text(v.value)])),...w.run_defaults.values}); setMissing(w.run_defaults.missing_values); setInstructions(w.run_defaults.instructions); setHydratedId(w.id)
  }
  async function search(query = message, filters: {period?:string;source?:string} = {}) {
    if (!query.trim() || busy) return
    const request = ++version.current; go(href.memories()); setMessage(query); setResults(null); setBusy('search'); setError(''); const started = performance.now()
    try { const tasks = await api<Task[]>('/tasks/search', { message: query, ...filters }); if (request === version.current) { setResults(tasks); setSearchTime((performance.now() - started) / 1000); void refresh() } } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }
  // Draft mode: a task with no saved twin. Nothing is saved until the user presses Save.
  async function reconstruct(task: Task) {
    setDraftTask(task); setWorkflow(null); setInstructions(''); setMissing({}); setValues({}); setHydratedId(null); setUnavailable(null); setBusy('reconstruct'); setError('')
    try {
      let w: Workflow; try { w = await api<Workflow>(`/tasks/${task.id}/workflow`) } catch(e) { if(!(e instanceof ApiError)||e.status!==404)throw e; w = await api<Workflow>(`/tasks/${task.id}/reconstruct`, {}) }
      const shown = routeRef.current; if (shown.page !== 'workflow' || shown.id !== task.id) return
      setWorkflow(w); setValues(Object.fromEntries(Object.entries(w.historical_values).map(([k,v]) => [k, text(v.value)]))); setHydratedId(task.id)
    } catch (e) { setUnavailable(task.id); setError((e as Error).message) } finally { setBusy(''); void refresh() }
  }
  // Resolve a workflows/<id> route that is not in the library: a saved workflow, else a task (legacy link or draft).
  async function resolveWorkflowRoute(id: string) {
    try { upsert(await api<SavedWorkflow>(`/workflows/${encodeURIComponent(id)}`)); return } catch (e) { if (!(e instanceof ApiError) || e.status !== 404) { setUnavailable(id); setError((e as Error).message); return } }
    try {
      const task = saved.find(t => t.id === id) ?? await api<Task>(`/tasks/${encodeURIComponent(id)}`)
      const twin = libraryRef.current.find(w => w.task.id === task.id)
      if (twin) go(href.workflow(twin.id), true); else await reconstruct(task)
    } catch (e) { setUnavailable(id); if (!(e instanceof ApiError) || e.status !== 404) setError((e as Error).message) }
  }
  // Every click on a workflow, from any page, lands on #/workflows/<savedId>. A task without a saved twin opens as a draft at #/workflows/<taskId>.
  function openWorkflow(ref: WorkflowRef) {
    if (ref.workflowId) { go(href.workflow(ref.workflowId)); return }
    if (!ref.taskId) return
    const twin = library.filter(w => w.task.id === ref.taskId).sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
    go(href.workflow(twin ? twin.id : ref.taskId))
  }

  const reviewedSaved = workflowId ? library.find(w => w.id === workflowId) ?? (fetchedSaved?.id === workflowId ? fetchedSaved : null) : null
  const task = reviewedSaved ? { ...reviewedSaved.task, title: reviewedSaved.title } : draftTask?.id === workflowId ? draftTask : null
  const plan = reviewedSaved ? workflowPlan(reviewedSaved) : draftTask?.id === workflowId ? workflow : null
  function requestValues() { return {values:Object.fromEntries(Object.entries(values).filter(([k,v])=>v!==text(plan?.historical_values[k]?.value)||reviewedSaved?.run_defaults.values[k]!==undefined)),missing_values:missing,instructions} }
  const hydrated = !!workflowId && hydratedId === workflowId
  const sameDefaults = !!reviewedSaved && reviewedSaved.run_defaults.instructions === instructions && sameJson(entries(reviewedSaved.run_defaults.values), entries(requestValues().values)) && sameJson(entries(reviewedSaved.run_defaults.missing_values), entries(missing))
  const definitionApproved = sameDefaults && reviewedSaved!.approved_revision === reviewedSaved!.revision
  async function persistWorkflow() {
    if(!task||!plan)throw new Error('Open a workflow first.')
    const previous=reviewedSaved
    const w=previous?await api<SavedWorkflow>(`/workflows/${previous.id}`,{expected_revision:previous.revision,run_defaults:requestValues()},'PATCH'):await api<SavedWorkflow>('/workflows',{task_id:task.id,defaults:requestValues()})
    upsert(w);setHydratedId(w.id)
    const shown = routeRef.current; if (shown.page === 'workflow' && shown.id !== w.id) go(href.workflow(w.id), true)
    return w
  }
  async function saveWorkflow() {setBusy('save');setError('');try{await persistWorkflow();setToast('Saved');await refresh()}catch(e){setError((e as Error).message)}finally{setBusy('')}}
  async function approveWorkflow() {setBusy('approve-workflow');setError('');try{const w=await persistWorkflow();const approved=await api<SavedWorkflow>(`/workflows/${w.id}/approve`,{expected_revision:w.revision});upsert(approved);setToast('Approved');await refresh()}catch(e){setError((e as Error).message)}finally{setBusy('')}}
  async function workflowEdited(w: SavedWorkflow) { upsert(w); hydrate(w); go(href.workflow(w.id), true); await refresh() }
  async function toggleSchedule(s: Schedule) { try { const {workflow_id,frequency,local_date,local_time,timezone,notifications}=s; await api(`/schedules/${s.id}`,{workflow_id,frequency,local_date,local_time,timezone,notifications,enabled:!s.enabled},'PATCH'); await refresh() } catch(e) { setError((e as Error).message) } }
  async function feedback(verdict:'looks_good'|'something_wrong',notes:string) {if(!run)return;setBusy('feedback');try{setRun(await api<Run>(`/runs/${run.id}/feedback`,{verdict,notes}));setToast('Your result review was saved.')}catch(e){setError((e as Error).message)}finally{setBusy('')}}
  async function openRun(id: string) {
    try { const selected = await api<Run>(`/runs/${id}`); setRun(selected); go(href.workflow(selected.workflow_id || selected.task_id)) }
    catch(e) { setError((e as Error).message) }
  }
  async function execute() {
    if (!task || !plan || busy || !definitionApproved) return
    setBusy('execute'); setError('')
    try { const r = await api<Run>(reviewedSaved?`/workflows/${reviewedSaved.id}/execute`:`/tasks/${task.id}/execute`, { ...requestValues(), auto_approve: autoApprove }); setAutoApprove(false); setRun(r); void refresh() } catch(e) { setError((e as Error).message) } finally { setBusy('') }
  }
  async function decide(approve: boolean) { if (!run?.pending_action || busy) return; setBusy('approval'); try { await api(`/runs/${run.id}/approval`, { action_id: run.pending_action.id, approve }); setRun(await api<Run>(`/runs/${run.id}`)) } catch(e) { setError((e as Error).message) } finally { setBusy('') } }
  async function stop(id = run?.id) { if (!id) return; try { setRun(await api<Run>(`/runs/${id}/stop`, {})); void refresh() } catch(e) { setError((e as Error).message) } }

  // Legacy hashes are rewritten in place (location.replace) so Back never loops.
  useEffect(() => {
    const legacy = legacyRedirect(path); if (legacy) { go(legacy, true); return }
    if (route.page === 'schedule' && route.id && libraryLoaded && schedulesLoaded && !schedules.some(s => s.id === route.id) && library.some(w => w.id === route.id)) go(href.scheduleNew(route.id), true)
  }, [path, libraryLoaded, schedulesLoaded])
  // Leaving the workflow route drops the transient draft.
  useEffect(() => { resolving.current = ''; if (route.page !== 'workflow') clearDraft() }, [route.page === 'workflow' ? route.id : ''])
  // Hydrate or resolve the workflow page. The guard ref stops library/memory refreshes from re-running the lookup.
  useEffect(() => {
    if (route.page !== 'workflow') return
    const id = route.id
    const w = libraryRef.current.find(x => x.id === id) ?? (fetchedSaved?.id === id ? fetchedSaved : null)
    if (w) { if (hydratedId !== id) hydrate(w); return }
    if (!libraryLoaded || resolving.current === id || busy) return
    resolving.current = id; void resolveWorkflowRoute(id)
  }, [path, library, libraryLoaded, hydratedId, fetchedSaved, busy])
  // Deep-linked run drawers load on route change only; the 15s refresh never reopens a closed drawer.
  useEffect(() => { if (route.page === 'runs') { if (route.id) void openRun(route.id); else go(href.workflows(), true) }
    if (route.page === 'settings') go(href.workflows(), true) }, [path])

  // Reopening a workflow restores its own latest run and its final report.
  useEffect(() => {
    if (route.page !== 'workflow') return
    if (run && (run.workflow_id === route.id || (!run.workflow_id && run.task_id === route.id))) return
    const latest = runs.find(r => r.workflow_id === route.id || (!r.workflow_id && r.task_id === route.id))
    if (!latest) return
    let cancelled = false
    api<Run>(`/runs/${latest.id}`).then(detail => { if (!cancelled) setRun(detail) }).catch(e => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [workflowId, runs, run?.id])

  const currentRun = runs.find(r => active(r.status)) || (run && active(run.status) ? run : null)
  const workflowRun = route.page === 'workflow' && run && (run.workflow_id === route.id || (!run.workflow_id && run.task_id === route.id)) ? run : null
  return <div className="app-shell"><Sidebar page={page} health={health} go={go}/><main className="main-shell">
    {error && <div className="error-banner" role="alert"><p>{error}</p><button className="icon-button" onClick={() => setError('')} aria-label="Dismiss error"><X size={19}/></button></div>}
    {currentRun && currentRun.id !== workflowRun?.id && <button className="active-banner" onClick={() => void openRun(currentRun.id)}><Play size={16}/> {currentRun.status === 'awaiting_approval' ? 'Run awaiting approval' : 'Run in progress'} <span>· Open <ArrowRight size={16}/></span></button>}
    <Chat refresh={refresh} visible={page === 'chat'} openWorkflow={openWorkflow}/><div key={route.page} className="page-enter">
    {page === 'home' && <Home loaded={libraryLoaded && memoriesLoaded} library={library} saved={saved} runs={runs} schedules={schedules} night={night} go={go} openWorkflow={openWorkflow} openRun={openRun}/>}
    {page === 'memories' && <Memories message={message} setMessage={setMessage} search={search} results={results} saved={saved} openWorkflow={openWorkflow} busy={busy} seconds={seconds} searchTime={searchTime} loaded={memoriesLoaded} loadError={memoryError} browse={()=>setResults(null)}/>}
    {route.page === 'workflows' && <Workflows loaded={libraryLoaded} loadError={libraryError} library={library} openWorkflow={openWorkflow} refresh={refresh} go={go}/>}
    {route.page === 'workflow' && <WorkflowPage key={route.id} id={route.id} mode={route.mode} saved={reviewedSaved} task={task} plan={plan} ready={hydrated} unavailable={unavailable === route.id} values={values} setValues={setValues} missing={missing} setMissing={setMissing} instructions={instructions} setInstructions={setInstructions} autoApprove={autoApprove} setAutoApprove={setAutoApprove} approved={definitionApproved} dirty={!!reviewedSaved && hydrated && !sameDefaults} busy={busy} seconds={seconds} available={!!health?.desktop_available && !currentRun} save={saveWorkflow} approve={approveWorkflow} execute={execute} runs={runs} schedules={schedules} openRun={openRun} activity={workflowRun ? <WorkflowActivity run={workflowRun} busy={!!busy} decide={decide} stop={stop} feedback={feedback}/> : null} toggleSchedule={toggleSchedule} edited={workflowEdited} refresh={refresh} go={go}/>}
    {page === 'record' && <RecordPage go={go} openWorkflow={openWorkflow} notify={setToast}/>}
    {route.page === 'schedule' && <SchedulePage notify={setToast} initialWorkflowId={route.newFor ?? ''} editId={route.id} library={library} go={go} openWorkflow={openWorkflow}/>}
    {route.page === 'nightshift' && <NightShift go={go} openWorkflow={openWorkflow} openRun={openRun} refresh={refresh} notify={setToast}/>}
    </div>
  </main>{toast && <div className="toast" role="status"><Sparkles size={18}/>{toast}<button className="icon-button" onClick={() => setToast('')} aria-label="Dismiss notification"><X size={16}/></button></div>}</div>
}
