import type { Run, SavedWorkflow, Schedule, Task } from './types'

// Canonical hashes: #/home, #/memories[/id], #/workflows[/id[/edit]], #/runs[/id], #/schedule[/id | /new/workflowId], #/nightshift, #/record, #/settings, #/chat
export type WorkflowRef = { workflowId?: string | null; taskId?: string | null }
export type Route =
  | { page: 'home' } | { page: 'chat' } | { page: 'record' } | { page: 'settings' } | { page: 'nightshift' }
  | { page: 'memories'; id?: string }
  | { page: 'workflows'; kind: 'list' }
  | { page: 'workflow'; id: string; mode?: 'edit' }
  | { page: 'runs'; id?: string }
  | { page: 'schedule'; id?: string; newFor?: string }

const decode = (s: string) => { try { return decodeURIComponent(s) } catch { return s } }
const enc = encodeURIComponent
const segments = (hash: string) => hash.replace(/^#?\/?/, '').split('/').filter(Boolean).map(decode)

export function parseRoute(hash: string): Route {
  const [page, a, b] = segments(hash)
  switch (page) {
    case 'chat': return { page: 'chat' }
    case 'record': return { page: 'record' }
    case 'settings': return { page: 'settings' }
    case 'nightshift': return { page: 'nightshift' }
    case 'memories': return a ? { page: 'memories', id: a } : { page: 'memories' }
    case 'runs': return a ? { page: 'runs', id: a } : { page: 'runs' }
    case 'schedule': return a === 'new' && b ? { page: 'schedule', newFor: b } : a ? { page: 'schedule', id: a } : { page: 'schedule' }
    case 'workflows': {
      if ((a === 'view' || a === 'saved') && b) return { page: 'workflow', id: b }   // legacy aliases
      return a ? { page: 'workflow', id: a, ...(b === 'edit' ? { mode: 'edit' as const } : {}) } : { page: 'workflows', kind: 'list' }
    }
    default: return { page: 'home' }
  }
}

/** Canonical path for a legacy hash (workflows/view/<id>, workflows/saved/<id>), or null when the hash is already canonical. */
export function legacyRedirect(hash: string): string | null {
  const [page, a, b] = segments(hash)
  return page === 'workflows' && (a === 'view' || a === 'saved') && b ? href.workflow(b) : null
}

// Paths are returned without the leading "#/" so they can be passed straight to go().
export const href = {
  home: () => 'home',
  memories: (id?: string) => id ? `memories/${enc(id)}` : 'memories',
  workflows: () => 'workflows',
  workflow: (id: string, edit = false) => `workflows/${enc(id)}${edit ? '/edit' : ''}`,
  run: (id?: string) => id ? `runs/${enc(id)}` : 'runs',
  schedule: (id?: string) => id ? `schedule/${enc(id)}` : 'schedule',
  scheduleNew: (workflowId: string) => `schedule/new/${enc(workflowId)}`,
  nightshift: () => 'nightshift',
  record: () => 'record',
  settings: () => 'settings',
  chat: () => 'chat',
}
export const link = (path: string) => `#/${path}`

/** Which saved workflow or task does this item belong to? SavedWorkflow > workflow_id > task_id > own id (Task). */
export function workflowRef(x: Task | SavedWorkflow | Run | Schedule): WorkflowRef {
  if ('run_defaults' in x) return { workflowId: x.id, taskId: x.task?.id }
  if ('workflow_id' in x && x.workflow_id) return { workflowId: x.workflow_id }
  if ('task_id' in x) return x.task_id ? { taskId: x.task_id } : {}
  if ('frequency' in x) return {}
  return { taskId: x.id }
}
