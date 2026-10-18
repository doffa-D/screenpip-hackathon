import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { MessageSquare, CalendarDays, MoonStar, ChevronRight, Clock3, FileText, Layers3, LoaderCircle, Monitor, Play, ShieldCheck, CircleDot, X } from 'lucide-react'
import type { Evidence, Health, Run, SavedWorkflow, Schedule, Task } from './types'
import { workflowPlan } from './workflow-plan'
import { workflowRef } from './routes'
import type { WorkflowRef } from './routes'
import melonLogo from './assets/melon-logo.png'

export const date = (s: string) => new Date(s).toLocaleString([], { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
export const human = (s: string) => s.replaceAll('_', ' ')
export const cap = (s: string) => { const t = human(s); return t.charAt(0).toUpperCase() + t.slice(1) }
export const text = (v: unknown) => typeof v === 'string' ? v : JSON.stringify(v, null, 2)
export const active = (s: string) => ['running', 'awaiting_approval', 'stopping'].includes(s)
export const duration = (s: number) => s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`
export const navItems = [ ['chat', 'Chat', MessageSquare], ['memories', 'Memories', Clock3], ['workflows', 'Workflows', Layers3], ['record', 'Record', CircleDot], ['schedule', 'Schedule', CalendarDays], ['nightshift', 'Night shift', MoonStar] ] as const
export type Page = typeof navItems[number][0] | 'home' | 'runs' | 'settings'
type OpenWorkflow = (ref: WorkflowRef) => void

export function Sidebar({ page, health, go }: { page: Page; health?: Health | null; go: (p: string) => void }) {
  return <aside className="sidebar"><button className="brand" onClick={() => go('home')} aria-label="Melon home"><span className="brand-logo-wrap"><img src={melonLogo} alt="Melon" className="brand-logo" /></span><b>Melon</b></button><nav aria-label="Main navigation">{navItems.map(([key, name, Icon]) => <a href={`#/${key}`} aria-label={name} aria-current={page === key ? 'page' : undefined} className={`nav-item ${page === key ? 'selected' : ''}`} key={key}><Icon size={22}/><span>{name}</span></a>)}</nav></aside>
}
export function PageHeader({ title, action }: { title: string; action?: ReactNode }) {
  return <header className="page-head"><h1>{title}</h1>{action && <div className="page-head-action">{action}</div>}</header>
}
export function Section({ title, subtitle, badge, action, children, className = '' }: { title: string; subtitle?: string; icon?: ReactNode; badge?: ReactNode; action?: ReactNode; children?: ReactNode; className?: string }) {
  return <section className={`section ${className}`}><div className="section-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{badge}{action && <div className="section-action">{action}</div>}</div>{children}</section>
}
export function AppIcon({ title, small = false }: { title: string; small?: boolean }) {
  const lower = title.toLowerCase(); const kind = /email|mail|gmail/.test(lower) ? 'mail' : /notepad|note/.test(lower) ? 'note' : /browser|chrome|research|github/.test(lower) ? 'browser' : 'doc'
  return <span className={`app-icon ${kind} ${small ? 'small' : ''}`} aria-hidden="true">{kind === 'mail' ? <svg viewBox="0 0 32 26"><path d="M3 23V5l13 10L29 5v18" fill="none" stroke="#4285f4" strokeWidth="5" strokeLinejoin="round"/><path d="M3 23V5l13 10L29 5v18" fill="none" stroke="#34a853" strokeWidth="5" strokeDasharray="18 38 18"/><path d="M3 5l13 10L29 5" fill="none" stroke="#ea4335" strokeWidth="5" strokeLinejoin="round"/></svg> : kind === 'browser' ? <Monitor/> : kind === 'note' ? <FileText fill="#76c4ff"/> : <FileText fill="#3488ff"/>}</span>
}

// Badges. StatusBadge covers run states plus the workflow variants approved | needs-review | missing.
const statusLabels: Record<string, string> = { approved: 'Approved', 'needs-review': 'Needs review', missing: 'Missing details', awaiting_approval: 'Needs approval', completed: 'Completed', running: 'Running', stopping: 'Stopping', failed: 'Failed', blocked: 'Blocked', cancelled: 'Cancelled', interrupted: 'Interrupted' }
export const statusLabel = (s: string) => statusLabels[s] ?? cap(s)
export function StatusBadge({ status }: { status: string }) { return <span className={`badge status-${status}`}><i className="dot"/>{statusLabel(status)}</span> }
export function ApprovalBadge({ approved, missing = false }: { approved: boolean; missing?: boolean }) { return <StatusBadge status={missing ? 'missing' : approved ? 'approved' : 'needs-review'}/> }
export function DemoBadge() { return <span className="badge demo-badge" title="Example data, not from your history.">Demo</span> }

export function EvidenceList({ evidence, expanded = false }: { evidence: Evidence[]; expanded?: boolean }) {
  return <details className="evidence" open={expanded || undefined}><summary><FileText size={15}/>{evidence.length} {evidence.length === 1 ? 'source' : 'sources'}</summary><div>{evidence.map((e, i) => <blockquote key={i}><span className="source-label">{e.source_kind === 'original_activity' ? 'Original activity' : human(e.source_kind)}</span><p>{e.quote}</p>{[...new Set([...e.quote.matchAll(/(?:screenpipe:\/\/frame\/|frame_id[=:]\s*)(\d+)/g)].map(m=>m[1]))].map(id=><a className="link-button evidence-source-link" key={id} href={`screenpipe://frame/${id}`} target="_blank" rel="noreferrer">Open original frame {id}</a>)}<details className="diagnostics"><summary>Source details</summary><code>{e.call_id}</code></details></blockquote>)}</div></details>
}

// Rows. ItemRow stretches its main button over the whole row, so trailing controls (e.g. a Toggle) are siblings rather than nested buttons.
export function ItemRow({ icon, title, meta, badge, trailing, onOpen }: { icon?: ReactNode; title: string; meta?: string; badge?: ReactNode; trailing?: ReactNode; onOpen?: () => void }) {
  return <div className="item-row"><button type="button" className="item-row-main" onClick={onOpen} disabled={!onOpen}>{icon}<span className="item-row-copy"><strong>{title}</strong>{meta && <small className="meta">{meta}</small>}</span>{badge}</button>{trailing && <span className="item-row-trailing">{trailing}</span>}{onOpen && <ChevronRight className="item-row-chevron" size={18} aria-hidden="true"/>}</div>
}
export function WorkflowRow({ w, onOpen }: { w: SavedWorkflow; onOpen: () => void }) {
  return <ItemRow icon={<AppIcon title={w.title} small/>} title={w.title} meta={`${workflowPlan(w).steps.length} steps · ${date(w.updated_at)}`} badge={<>{w.origin === 'demo' && <DemoBadge/>}<ApprovalBadge approved={w.approved_revision === w.revision}/></>} onOpen={onOpen}/>
}
type TaskLike = { id: string; title: string; timestamp?: string; summary?: string; origin?: string }
/** `taskId` overrides which task to open (null = none), e.g. for a recording segment whose task id differs from its own id. */
export function TaskRow({ task, openWorkflow, meta, badge, taskId }: { task: TaskLike; openWorkflow: OpenWorkflow; meta?: string; badge?: ReactNode; taskId?: string | null }) {
  const ref: WorkflowRef = taskId === undefined ? workflowRef(task as Task) : taskId ? { taskId } : {}
  return <ItemRow icon={<AppIcon title={task.title} small/>} title={task.title} meta={meta ?? [task.timestamp && date(task.timestamp), task.summary].filter(Boolean).join(' · ')} badge={<>{task.origin === 'demo' && <DemoBadge/>}{badge}</>} onOpen={taskId === null ? undefined : () => openWorkflow(ref)}/>
}
export function RunRow({ run, openRun }: { run: Run; openRun: (id: string) => void }) {
  return <ItemRow icon={<AppIcon title={run.title} small/>} title={run.title} meta={`${date(run.started_at)} · ${run.elapsed_seconds !== null ? duration(run.elapsed_seconds) : 'In progress'}`} badge={<>{run.origin === 'demo' && <DemoBadge/>}<StatusBadge status={run.status}/></>} onOpen={() => openRun(run.id)}/>
}
export function ScheduleRow({ s, title, openWorkflow, trailing }: { s: Schedule; title?: string; openWorkflow: OpenWorkflow; trailing?: ReactNode }) {
  return <ItemRow icon={<AppIcon title={title ?? s.title} small/>} title={title ?? s.title} meta={`${cap(s.frequency)} · ${s.next_run_at ? date(s.next_run_at) : 'No future run'}`} badge={s.origin === 'demo' ? <DemoBadge/> : undefined} trailing={trailing} onOpen={() => openWorkflow(workflowRef(s))}/>
}
/** Link-button to a workflow; renders nothing when there is no workflow or task to resolve. */
export function WorkflowLink({ workflowId, taskId, label = 'Open workflow', openWorkflow }: WorkflowRef & { label?: string; openWorkflow: OpenWorkflow }) {
  if (!workflowId && !taskId) return null
  return <button type="button" className="link-button" onClick={() => openWorkflow({ workflowId, taskId })}>{label}</button>
}

export function EmptyState({ title, children, action, icon }: { title: string; children?: ReactNode; action?: ReactNode; icon?: ReactNode }) { return <div className="empty-state">{icon && <span className="empty-icon">{icon}</span>}<h3>{title}</h3>{children && <p>{children}</p>}{action}</div> }
export function LoadingState({ title, seconds }: { title?: string; seconds?: number }) { return <div className="loading-state" role="status" aria-label={title ?? 'Loading'}><LoaderCircle className="spin" size={26}/>{!!seconds && seconds >= 5 && <span className="meta">{seconds}s</span>}</div> }
export function Toggle({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) { return <button type="button" role="switch" aria-checked={checked} aria-label={label} className="toggle" disabled={disabled} onClick={() => onChange(!checked)}><span/></button> }
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { const previous = document.activeElement as HTMLElement; ref.current?.focus(); const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); if (e.key === 'Tab') { const els = ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input,textarea,select,a[href],[tabindex="0"]'); if (!els?.length) return; const first = els[0], last = els[els.length - 1]; if (e.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { e.preventDefault(); last.focus() } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() } } }; document.addEventListener('keydown', handler); return () => { document.removeEventListener('keydown', handler); previous?.focus() } }, [])
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}><div ref={ref} className="modal" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}><div className="section-heading"><h2>{title}</h2><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X/></button></div>{children}</div></div>
}
export function PrivacyNote() { return <div className="privacy-note"><ShieldCheck size={23}/><div><strong>Your history stays local. You stay in control.</strong><small>Relevant context is sent to your configured AI provider during background sync and when you search, reconstruct, or run a workflow.</small></div></div> }
