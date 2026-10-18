import { useEffect, useRef, useState } from 'react'
import { Check, MoonStar, Play, RefreshCw, ThumbsDown, TriangleAlert, Undo2 } from 'lucide-react'
import { api } from './api'
import type { NightEvidence, NightProposal, NightReport, NightReportItem, NightScope, NightSettings, NightStatus } from './types'
import type { WorkflowRef } from './routes'
import { href } from './routes'
import { date, DemoBadge, EmptyState, ItemRow, LoadingState, Modal, PageHeader, Section, StatusBadge, Toggle } from './components'

type Props = { go: (p: string) => void; openWorkflow: (ref: WorkflowRef) => void; openRun: (id: string) => void; refresh: () => void | Promise<void>; notify: (s: string) => void }
type Scoped = Pick<NightScope, 'allowed_hosts' | 'allowed_apps' | 'may_finalize' | 'max_actions' | 'used'>

const hm = (t: string) => t.slice(0, 5)
const clock = (t: string) => { const [h, m] = t.split(':').map(Number); return new Date(2000, 0, 1, h, m).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) }
const list = (s: string) => [...new Set(s.split(/[,\n;]+/).map(x => x.trim()).filter(Boolean))]
const host = (s: string) => s.toLowerCase().replace(/^[a-z]+:\/\//, '').split(/[/?#]/)[0].replace(/\.$/, '')
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
const toForm = (s: NightSettings) => ({ ...s, window_start: hm(s.window_start), window_end: hm(s.window_end) })

// [label, tone] for each kind of morning result, in everyday words.
const stateInfo: Record<string, [string, string]> = { completed: ['Done', 'ok'], prepared: ['Ready for you to check', 'ok'], needs_you: ['Needs you', 'warn'], failed: ['Didn’t work', 'bad'], skipped: ['Skipped', 'neutral'], missed: ['Didn’t run', 'neutral'] }
function NightBadge({ state }: { state: string }) { const [label, tone] = stateInfo[state] ?? [state.replaceAll('_', ' '), 'neutral']; return <span className={`badge ns-badge ns-${tone}`}><i className="dot"/>{label}</span> }

const joinWords = (items: string[]) => items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
/** Where Melon may work, as one readable sentence plus what it will not do. */
function Where({ scope }: { scope: Scoped }) {
  const where = [...scope.allowed_apps, ...scope.allowed_hosts]
  return <ul className="ns-where"><li>Works in: {where.length ? joinWords(where) : 'nothing listed'}</li><li>{scope.may_finalize ? 'May press final buttons such as Send' : 'Stops before anything is sent, deleted or paid'}</li><li>Up to {plural(scope.max_actions, 'step')}{scope.used ? ` (${scope.used} used)` : ''}</li></ul>
}
function Evidence({ items }: { items: NightEvidence[] }) {
  if (!items.length) return null
  return <details className="evidence ns-evidence"><summary>What Melon saw</summary><div>{items.map(e => <blockquote key={e.id}><span className="source-label">{[e.app, e.window].filter(Boolean).join(' · ') || 'Activity'}</span><p><strong>{e.title}</strong></p>{e.summary && <p>{e.summary}</p>}<small>{date(e.timestamp)}</small></blockquote>)}</div></details>
}

export function NightShift({ go, openWorkflow, openRun, refresh, notify }: Props) {
  const [status, setStatus] = useState<NightStatus | null>(null)
  const [proposals, setProposals] = useState<NightProposal[]>([])
  const [report, setReport] = useState<NightReport | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [form, setForm] = useState<ReturnType<typeof toForm> | null>(null)
  const [touched, setTouched] = useState(false)
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [wrong, setWrong] = useState('')
  const [approving, setApproving] = useState<NightProposal | null>(null)
  const [hosts, setHosts] = useState('')
  const [apps, setApps] = useState('')
  const [finalize, setFinalize] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [modalError, setModalError] = useState('')
  const alive = useRef(true)
  async function load() {
    const [s, p, r] = await Promise.all([api<NightStatus>('/nightshift/status'), api<NightProposal[]>('/nightshift/proposals'), api<NightReport>('/nightshift/report')])
    if (!alive.current) return
    setStatus(s); setProposals(p); setReport(r); setLoaded(true); setError('')
  }
  useEffect(() => { alive.current = true; const poll = () => { void load().catch(e => { if (alive.current) { setError((e as Error).message); setLoaded(true) } }) }; poll(); const t = setInterval(poll, 5000); return () => { alive.current = false; clearInterval(t) } }, [])
  useEffect(() => { if (status && !touched) setForm(toForm(status.settings)) }, [status, touched])
  async function act(label: string, fn: () => Promise<string | void>) {
    if (busy) return; setBusy(label); setError('')
    try { const message = await fn(); await load(); void refresh(); if (message) notify(message) } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }
  const saveSettings = (next: NightSettings) => api('/nightshift/settings', { ...next, window_start: hm(next.window_start), window_end: hm(next.window_end) }, 'PATCH')
  const toggle = (enabled: boolean) => status && act('toggle', async () => { await saveSettings({ ...status.settings, enabled }); return enabled ? 'Night shift is on' : 'Night shift is off' })
  const save = () => status && form && act('save', async () => { await saveSettings({ ...form, enabled: status.settings.enabled }); setTouched(false); return 'Settings saved' })
  const change = (patch: Partial<NonNullable<typeof form>>) => { setTouched(true); setForm(f => f && { ...f, ...patch }) }
  const openApprove = (p: NightProposal) => { setApproving(p); setHosts((p.suggested_scope?.allowed_hosts ?? []).join(', ')); setApps((p.suggested_scope?.allowed_apps ?? p.apps ?? []).join(', ')); setFinalize(false); setAdvanced(false); setModalError('') }
  async function approve() {
    if (!approving || busy) return
    const h = [...new Set(list(hosts).map(host))].filter(Boolean), a = list(apps)
    if (!a.length) { setAdvanced(true); setModalError('Tell Melon which app it may use, for example Google Chrome.'); return }
    if (h.length > 10 || a.length > 10) { setAdvanced(true); setModalError('Please keep it to 10 websites and 10 apps at most.'); return }
    setBusy('approve'); setModalError('')
    try { await api(`/nightshift/proposals/${approving.id}/approve`, { ...(h.length ? { allowed_hosts: h } : {}), allowed_apps: a, may_finalize: finalize }); setApproving(null); await load(); void refresh(); notify('Okay, Melon will do this tonight') }
    catch (e) { setModalError((e as Error).message) } finally { setBusy('') }
  }
  const review = (id: string, verdict: 'looks_good' | 'something_wrong') => act(`review-${id}`, async () => { await api(`/nightshift/proposals/${id}/review`, { verdict, notes: (notes[id] ?? '').trim() }); setNotes(n => ({ ...n, [id]: '' })); setWrong(''); return verdict === 'looks_good' ? 'Thanks!' : 'Thanks, Melon will remember this' })

  const byId = new Map(proposals.map(p => [p.id, p]))
  const tonight = proposals.filter(p => p.status === 'approved' || p.status === 'running')
  const noticed = proposals.filter(p => p.status === 'suggested')
  const history = proposals.filter(p => ['reviewed', 'dismissed', 'expired'].includes(p.status))
  const on = !!status?.settings.enabled
  const items = report?.items ?? []
  const analysis = status?.analysis
  const hours = status ? `${clock(status.settings.window_start)} to ${clock(status.settings.window_end)}` : ''

  function reportCard(i: NightReportItem) {
    const runId = byId.get(i.id)?.run_id ?? i.run_id
    const passive = i.state === 'skipped' || i.state === 'missed'
    const steps = i.steps
    return <article className={`workflow-card ns-card ns-simple ${i.needs_attention ? 'ns-attention' : ''}`} key={i.id}>
      <div className="ns-status"><NightBadge state={i.state}/>{i.origin === 'demo' && <DemoBadge/>}</div>
      <h3>{i.title}</h3>
      <p className="ns-plain">{i.did || 'Nothing was done.'}</p>
      {i.next_step && <p className="ns-next"><b>What to do:</b> {i.next_step}</p>}
      {passive ? <div className="button-row"><button className="secondary" disabled={!!busy} onClick={() => void review(i.id, 'looks_good')}><Check size={16}/> Got it</button></div>
        : wrong === i.id ? <><label className="field ns-notes"><span>What went wrong? (optional)</span><input autoFocus value={notes[i.id] ?? ''} maxLength={4000} placeholder="A few words are enough" onChange={e => setNotes(n => ({ ...n, [i.id]: e.target.value }))}/></label>
            <div className="button-row"><button className="primary" disabled={!!busy} onClick={() => void review(i.id, 'something_wrong')}>Send</button><button className="secondary" onClick={() => setWrong('')}>Cancel</button></div></>
        : <div className="button-row ns-review"><button className="primary" disabled={!!busy} onClick={() => void review(i.id, 'looks_good')}><Check size={16}/> Looks good</button><button className="secondary" disabled={!!busy} onClick={() => setWrong(i.id)}><ThumbsDown size={16}/> Something’s wrong</button></div>}
      <details className="ns-more"><summary>See details</summary>
        <small className="ns-label">Why Melon did this</small><p>{i.plain || i.noticed}</p><Evidence items={i.evidence}/>
        {steps.actions_attempted > 0 && <><small className="ns-label">What it did</small><p>{steps.actions_completed} of {plural(steps.actions_attempted, 'step')} done{steps.checks_passed > 0 ? `, ${plural(steps.checks_passed, 'check')} passed` : ''}{steps.checks_failed > 0 ? `, ${plural(steps.checks_failed, 'check')} failed` : ''}.</p></>}
        {i.scope && <><small className="ns-label">Where it was allowed to work</small><Where scope={i.scope as Scoped}/></>}
        <div className="ns-links">{runId && <button className="link-button" onClick={() => openRun(runId)}>See every step</button>}{i.workflow_id && <button className="link-button" onClick={() => openWorkflow({ workflowId: i.workflow_id })}>Open the saved task</button>}{i.finished_at && <small>{date(i.finished_at)}</small>}</div>
      </details>
    </article>
  }
  function tonightCard(p: NightProposal) {
    const running = p.status === 'running'
    return <article className="workflow-card ns-card ns-simple" key={p.id}>
      <div className="ns-status">{running ? <StatusBadge status={p.run_status ?? 'running'}/> : <span className="badge ns-badge ns-ok"><i className="dot"/>Planned for tonight</span>}{p.origin === 'demo' && <DemoBadge/>}</div>
      <h3>{p.title}</h3>
      <p className="ns-plain">{running ? 'Melon is working on this right now.' : `Melon will get this ready between ${hours}. ${p.scope?.may_finalize ? 'It may also press the final button.' : 'It will stop before anything is sent, so you can check it first.'}`}</p>
      <div className="button-row">
        {p.run_id && <button className="secondary" onClick={() => openRun(p.run_id!)}>Watch it</button>}
        {!running && <><button className="secondary" disabled={!!busy} onClick={() => void act(`revoke-${p.id}`, async () => { await api(`/nightshift/proposals/${p.id}/revoke`, {}); return 'Cancelled. Nothing will happen tonight.' })}><Undo2 size={16}/> Cancel</button>
        {p.origin !== 'demo' && <button className="secondary" disabled={!!busy || !on} title={on ? 'Runs it now for up to 45 minutes, with the same limits' : 'Turn Night shift on first'} onClick={() => void act(`run-${p.id}`, async () => { await api(`/nightshift/proposals/${p.id}/run-now`, {}); return 'Started a practice run' })}><Play size={16}/> Try it now</button>}</>}
      </div>
      {p.scope && <details className="ns-more"><summary>See details</summary><small className="ns-label">Where Melon may work</small><Where scope={p.scope}/></details>}
    </article>
  }
  function noticedCard(p: NightProposal) {
    const e = p.eligibility
    const fixLabel = e.state === 'needs_approval' ? 'Check and approve the saved task' : e.state === 'needs_values' ? 'Fill in the missing details' : 'Open the saved task'
    const dismiss = (message: string) => void act(`dismiss-${p.id}`, async () => { await api(`/nightshift/proposals/${p.id}/dismiss`, {}); return message })
    const sure = p.confidence >= 0.8 ? 'Melon is quite sure' : 'Melon is fairly sure'
    return <article className="workflow-card ns-card ns-simple" key={p.id}>
      <div className="ns-status"><span className="badge">{p.kind === 'missed_next_step' ? 'Maybe forgotten' : 'Maybe unfinished'}</span>{p.origin === 'demo' && <DemoBadge/>}</div>
      <h3>{p.title}</h3>
      <p className="ns-plain">{p.plain || p.rationale}</p>
      {e.state === 'ready' ? <div className="button-row"><button className="primary" disabled={!!busy} onClick={() => openApprove(p)}><MoonStar size={16}/> Do this tonight</button><button className="secondary" disabled={!!busy} onClick={() => dismiss('Okay, Melon won’t suggest this for a while')}>Not now</button></div> :
        <><p className="ns-hint" role="status"><TriangleAlert size={15}/>{e.state === 'no_workflow' ? 'Melon doesn’t know how to do this yet. Show it once by saving this task, and it can help next time.' : e.detail}</p>
        <div className="button-row">{p.workflow_id ? <button className="secondary" onClick={() => openWorkflow({ workflowId: p.workflow_id })}>{fixLabel}</button> : <button className="secondary" onClick={() => go(href.memories())}>Teach Melon this task</button>}<button className="link-button" disabled={!!busy} onClick={() => dismiss('Okay, hidden')}>Not now</button></div></>}
      <details className="ns-more"><summary>Why does Melon think this?</summary><p>{p.rationale}</p><small className="meta">{sure} ({Math.round(p.confidence * 100)}%).</small><Evidence items={p.evidence}/></details>
    </article>
  }

  return <>
    <PageHeader title="Night shift" action={<button className="secondary" disabled={!!busy || !status} onClick={() => void act('analyze', async () => { const a = await api<{ new_suggestions?: number; note?: string }>('/nightshift/analyze', {}); return a?.note || (a?.new_suggestions ? plural(a.new_suggestions, 'new idea') : 'Checked: nothing new') })}><RefreshCw size={16} className={busy === 'analyze' ? 'spin' : ''}/> {busy === 'analyze' ? 'Checking…' : 'Look again'}</button>}/>
    {!loaded && <LoadingState title="Loading Night shift"/>}{error && <p className="notice" role="alert">{error}</p>}
    {status && <Section title="Let Melon help while you sleep" subtitle="Melon notices steps you usually do but forgot, and can get them ready overnight. You decide what it may do." badge={status.window.active ? <span className="badge ns-badge ns-ok"><i className="dot"/>Working hours now</span> : undefined}>
      <div className="setting-row"><div><strong>{on ? 'Night shift is on' : 'Night shift is off'}</strong><small className="meta ns-window">Melon works between {hours}</small></div><Toggle checked={on} disabled={!!busy} label="Turn Night shift on or off" onChange={v => void toggle(v)}/></div>
      {!status.desktop_unlocked && <p className="ns-warning" role="status"><TriangleAlert size={16}/>Your PC looks locked. Melon can only work if the PC is switched on and signed in (the screen can be off).</p>}
      {status.note && <p className="ns-warning" role="status"><TriangleAlert size={16}/>{status.note}</p>}
      {analysis && <small className="meta">Last checked {date(analysis.at)}.</small>}
      <details><summary>What Melon will and won’t do</summary><ul className="tips-list">
        <li>It only repeats tasks you have saved and approved.</li><li>You approve each task for one night only, and can cancel until it starts.</li><li>By default it gets things ready and stops before anything is sent, deleted or paid.</li><li>The PC must be on and signed in (the screen can be off).</li><li>If anything looks unexpected, it stops and tells you why in the morning.</li>
        <li><details><summary>More details</summary><ul>{status.limits.map(l => <li key={l}>{l}</li>)}</ul></details></li></ul></details>
    </Section>}

    {items.length > 0 && <Section title="While you were away" subtitle={report?.headline.replace('While you were away: ', '')} className="ns-report"><div className="ns-stack">{items.map(reportCard)}</div></Section>}

    {status && <Section title="Planned for tonight" subtitle="Each plan is for one night only.">
      {tonight.length ? <div className="ns-stack">{tonight.map(tonightCard)}</div> : <EmptyState title="Nothing planned for tonight.">Pick an idea below and Melon will get it ready overnight.</EmptyState>}
    </Section>}

    {status && <Section title="Melon noticed" subtitle="Things you might have forgotten or left unfinished.">
      {noticed.length ? <div className="ns-stack">{noticed.map(noticedCard)}</div> : <EmptyState title="Nothing new yet." action={<button className="secondary" disabled={!!busy} onClick={() => void act('analyze', async () => { await api('/nightshift/analyze', {}) })}>Look again</button>}>Melon needs to see your routine for a few days before it can tell what you usually do next.</EmptyState>}
    </Section>}

    {history.length > 0 && <details className="section ns-history"><summary>Earlier ({history.length})</summary><div className="item-list">{history.map(p => <ItemRow key={p.id} title={p.title} meta={`${date(p.finished_at ?? p.created_at)}${p.review ? ` · You said: ${p.review.verdict === 'looks_good' ? 'looked good' : 'something was wrong'}` : ''}${p.review?.notes ? ` · ${p.review.notes}` : ''}`} badge={<span className={`badge ns-badge ns-${p.status === 'reviewed' && p.review?.verdict === 'looks_good' ? 'ok' : p.status === 'reviewed' ? 'warn' : 'neutral'}`}>{p.status === 'reviewed' ? 'Checked' : p.status === 'dismissed' ? 'Not now' : 'Expired'}</span>} onOpen={p.run_id ? () => openRun(p.run_id!) : undefined}/>)}</div></details>}

    {status && form && <details className="section ns-history"><summary>Settings</summary>
      <div className="grid two"><label className="field"><span>Start working at</span><input type="time" value={form.window_start} onChange={e => change({ window_start: e.target.value })}/></label><label className="field"><span>Stop working at</span><input type="time" value={form.window_end} onChange={e => change({ window_end: e.target.value })}/></label></div>
      <details><summary>More options</summary>
        <label className="field"><span>Time zone</span><input value={form.timezone} onChange={e => change({ timezone: e.target.value })}/></label>
        <div className="grid two"><label className="field"><span>Most tasks in one night</span><input type="number" min={1} max={10} value={form.max_tasks_per_night} onChange={e => change({ max_tasks_per_night: Number(e.target.value) })}/></label><label className="field"><span>Most steps per task</span><input type="number" min={5} max={200} value={form.max_actions_per_task} onChange={e => change({ max_actions_per_task: Number(e.target.value) })}/></label></div></details>
      <div className="button-row"><button className="primary" disabled={!!busy || !touched || !form.window_start || !form.window_end || !form.timezone.trim()} onClick={() => void save()}>{busy === 'save' ? 'Saving…' : 'Save'}</button>{touched && <button className="secondary" onClick={() => setTouched(false)}>Undo changes</button>}</div>
    </details>}

    {approving && <Modal title="Do this tonight?" onClose={() => setApproving(null)}>
      <p><strong>{approving.title}</strong></p><p className="meta">{approving.plain || approving.rationale}</p>
      <div className="notice ns-summary"><b>Here’s the plan</b><ul>
        <li>Tonight between {hours}, Melon does this once.</li>
        <li>{finalize ? 'It may also press the final button, such as Send.' : 'It gets everything ready, then stops before anything is sent. You finish it in the morning.'}</li>
        <li>If anything looks unexpected, it stops and tells you why.</li>
        <li>This is for tonight only. You can cancel any time before it starts.</li></ul></div>
      <label className={`ns-check ${finalize ? 'ns-check-on' : ''}`}><input type="checkbox" checked={finalize} onChange={e => setFinalize(e.target.checked)}/><span><b>Let Melon press the final button too</b><small>Off is safer. When on, Melon can send, submit, pay or delete without asking you first. Only choose this if you fully trust this task.</small></span></label>
      <details open={advanced} onToggle={e => setAdvanced((e.target as HTMLDetailsElement).open)}><summary>Where Melon may work{apps ? `: ${apps}` : ''}</summary>
        <label className="field"><span>Apps</span><input value={apps} placeholder="Google Chrome" onChange={e => setApps(e.target.value)}/><small>Separate with commas. Melon will only use these apps.</small></label>
        <label className="field"><span>Websites</span><input value={hosts} placeholder="mail.google.com" onChange={e => setHosts(e.target.value)}/><small>Separate with commas. Any other website stops the task.</small></label></details>
      {modalError && <p className="ns-warning" role="alert"><TriangleAlert size={16}/>{modalError}</p>}
      <div className="button-row"><button className="secondary" onClick={() => setApproving(null)}>Cancel</button><button className="primary" disabled={!!busy} onClick={() => void approve()}>{busy === 'approve' ? 'Saving…' : 'Yes, do this tonight'}</button></div>
    </Modal>}
  </>
}
