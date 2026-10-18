import { useEffect, useState } from 'react'
import { Search } from 'lucide-react'
import type { Task } from './types'
import { api } from './api'
import { EmptyState, LoadingState, PageHeader, TaskRow } from './components'
import type { WorkflowRef } from './routes'

const memoryParams=(query:string,limit:number)=>new URLSearchParams({limit:String(limit),q:query})

type Props = {message:string;setMessage:(s:string)=>void;search:(s?:string)=>void;results:Task[]|null;saved:Task[];busy:string;seconds:number;searchTime:number|null;loaded:boolean;loadError:string;browse:()=>void;openWorkflow:(ref:WorkflowRef)=>void}
export function Memories({message,setMessage,search,results,saved,openWorkflow,busy,seconds,searchTime,loaded,loadError,browse}:Props) {
  const [query,setQuery]=useState('')
  const [sort,setSort]=useState('newest')
  const [items,setItems]=useState<Task[]>([])
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  useEffect(()=>{
    let alive=true
    setLoading(true)
    api<Task[]>(`/memories?${memoryParams(query,500)}`).then(v=>{if(alive){setItems(v);setError('')}}).catch(e=>{if(alive)setError(e.message)}).finally(()=>{if(alive)setLoading(false)})
    return()=>{alive=false}
  },[query,saved])
  const tasks=[...(results??items)].sort((a,b)=>(sort==='oldest'?1:-1)*(+new Date(a.timestamp)-+new Date(b.timestamp)))
  async function submit(){browse();setQuery(message);if(!message.trim())return;try{const local=await api<Task[]>(`/memories?${memoryParams(message,1)}`);if(!local.length)search(message)}catch(e){setError((e as Error).message)}}
  if(busy==='search')return <LoadingState title="Searching" seconds={seconds}/>
  const err=error||loadError
  return <>
    <PageHeader title="Memories"/>
    <form className="search-bar" role="search" onSubmit={e=>{e.preventDefault();void submit()}}><Search size={18} aria-hidden="true"/><input aria-label="Search memories" placeholder="Search memories" value={message} onChange={e=>setMessage(e.target.value)}/></form>
    <section className="section results-section"><div className="results-toolbar"><h2>{loading&&results===null?'Loading…':`${tasks.length} ${tasks.length===1?'memory':'memories'}`}{searchTime!==null&&results!==null&&<small>{searchTime.toFixed(1)}s</small>}</h2><label className="sort"><select aria-label="Sort memories" value={sort} onChange={e=>setSort(e.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label></div>
    {err&&<div className="error-banner" role="alert"><p>{err}</p></div>}
    <div className="memory-list">{tasks.map(t=><TaskRow key={t.id} task={t} openWorkflow={openWorkflow}/>)}</div>
    {!tasks.length&&!loading&&loaded&&<EmptyState title="No memories match."/>}</section>
  </>
}
