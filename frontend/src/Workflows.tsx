import { workflowPlan } from './workflow-plan'
import { useState } from 'react'
import { Search } from 'lucide-react'
import { EmptyState, PageHeader, WorkflowRow } from './components'
import { DemoSuggestions } from './DemoSuggestions'
import { Discovery } from './Discovery'
import type { SavedWorkflow } from './types'
import type { WorkflowRef } from './routes'

type Props = {
  loaded: boolean; loadError: string; library: SavedWorkflow[]
  go: (path: string) => void
  openWorkflow: (ref: WorkflowRef) => void; refresh: () => void
}

export function Workflows({ loaded, loadError, library, go, openWorkflow, refresh }: Props) {
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState('All workflows')
  const matching = library.filter(workflow => `${workflow.title} ${workflowPlan(workflow).goal} ${workflow.tags.join(' ')}`.toLowerCase().includes(query.toLowerCase()))
  return <>
    <PageHeader title="Workflows" action={<button className="secondary" onClick={() => go('memories')}>New</button>}/>
    <div className="workflow-library-toolbar">
      <div className="filters">{['All workflows', 'Suggested for you', 'Most repeated'].map(label => <button key={label} className={`chip ${tab === label ? 'chosen' : ''}`} aria-pressed={tab === label} onClick={() => setTab(label)}>{label}</button>)}</div>
    </div>
    <label className="workflow-library-search"><Search size={18}/><input aria-label="Search workflows" placeholder="Search workflows by name, goal, or tag" value={query} onChange={event => setQuery(event.target.value)}/></label>
    {tab === 'All workflows' ? <>
      {loadError && <p role="alert">{loadError}</p>}
      {!loaded ? <p role="status">Loading…</p> : matching.length ? <div className="workflow-library-list">{matching.map(workflow => <WorkflowRow key={workflow.id} w={workflow} onOpen={() => openWorkflow({ workflowId: workflow.id })}/>)}</div> : <EmptyState title={library.length ? 'No matching workflows' : 'No workflows yet. Save one from Memories.'}/>}
    </> : <><Discovery tab={tab} query={query} refresh={refresh} openWorkflow={openWorkflow}/><DemoSuggestions query={query} openWorkflow={openWorkflow}/></>}
  </>
}
