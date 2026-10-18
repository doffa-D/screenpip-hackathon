import { useEffect, useState } from 'react'
import { api } from './api'
import { DemoBadge, Section } from './components'
import type { WorkflowRef } from './routes'
type DemoPattern = {id:string;title:string;demo_occurrence_count:number;workflow_id:string;summary:string}
export function DemoSuggestions({query,openWorkflow}:{query:string;openWorkflow:(ref:WorkflowRef)=>void}) {
  const [items,setItems]=useState<DemoPattern[]>([])
  useEffect(()=>{let alive=true;api<DemoPattern[]>('/demo/patterns').then(data=>{if(alive)setItems(data)}).catch(()=>{});return()=>{alive=false}},[])
  if(!items.length)return null
  return <Section title="Demo examples"><div className="grid three">{items.filter(p=>p.title.toLowerCase().includes(query.toLowerCase())).map(p=><article className="workflow-card" key={p.id}><DemoBadge/><h3>{p.title}</h3><p>{p.summary}</p><small className="meta">{p.demo_occurrence_count} times</small><button className="secondary" onClick={()=>openWorkflow({workflowId:p.workflow_id})}>Open workflow</button></article>)}</div></Section>
}
