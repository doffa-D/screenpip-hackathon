import type { ReactNode } from 'react'
import { Clock3, Monitor, Info, ArrowRight } from 'lucide-react'
import { href, link } from './routes'
import type { WorkflowRef } from './routes'

export function FriendlyText({text}:{text:string}) {
 const inline=(line:string):ReactNode[]=>line.split(/(\*\*[^*]+\*\*)/g).map((part,i)=>part.startsWith('**')?<strong key={i}>{part.slice(2,-2)}</strong>:part)
 const blocks:ReactNode[]=[];let bullets:string[]=[]
 const flush=()=>{if(bullets.length){blocks.push(<ul key={blocks.length}>{bullets.map((line,i)=><li key={i}>{inline(line)}</li>)}</ul>);bullets=[]}}
 for(const line of text.split('\n')){if(/^\s*[-•]\s+/.test(line)){bullets.push(line.replace(/^\s*[-•]\s+/,''));continue}flush();if(line.trim())blocks.push(<p key={blocks.length}>{inline(line.replace(/^#{1,4}\s+/,''))}</p>)}flush()
 return <div className="chat-prose">{blocks}</div>
}

type Result={operation?:string;status?:number;data?:unknown;cancelled?:boolean}
function appName(name:string){const names:Record<string,string>={'chrome.exe':'Google Chrome','ChatGPT.exe':'ChatGPT','Notepad.exe':'Notepad','pythonw.exe':'Python apps','python.exe':'Python','explorer.exe':'File Explorer','Antigravity.exe':'Antigravity','Antigravity-x64.exe':'Antigravity'};return names[name]||name.replace(/\.exe$/i,'')}
function minutes(value:number){return value>=60?`${Math.floor(value/60)}h ${Math.round(value%60)}m`:`${Math.round(value*10)/10} min`}
function ActivityCard({data}:{data:Record<string,unknown>}) {
 const summary=String(data.summary||'')
 const active=summary.match(/Authoritative active time:\s*([\d.]+) min/)
 const section=summary.split('\nApps:\n')[1]?.split('\n\n')[0]||''
 const apps=Array.from(section.matchAll(/^\s+(.+?):\s*([\d.]+) min/gm)).map(m=>({name:appName(m[1]),time:Number(m[2])})).filter(a=>a.time>0)
 const total=active?Number(active[1]):null
 const start=new Date(String(data.start_time)),end=new Date(String(data.end_time))
 const valid=!isNaN(start.getTime())&&!isNaN(end.getTime())
 const timeZone=String(data.timezone||'UTC')
 const format=(d:Date)=>d.toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone})
 return <section className="activity-answer"><div className="activity-answer-title"><Monitor size={18}/><strong>Your activity at a glance</strong></div>{valid&&<div className="activity-period">{format(start)} – {format(end)} · {timeZone}</div>}<div className="activity-total"><Clock3 size={20}/><div><strong>{total!==null?minutes(total):'Time unavailable'}</strong><span>Active computer time recorded</span></div></div>{apps.length>0&&<div className="activity-apps">{apps.slice(0,6).map((a,i)=><div className="activity-app" key={i}><div><span>{a.name}</span><strong>{minutes(a.time)}</strong></div><progress aria-label={`${a.name}: ${minutes(a.time)}`} max={total||Math.max(...apps.map(x=>x.time))} value={a.time}/></div>)}{apps.length>6&&<small>Plus {apps.length-6} other apps in the source record.</small>}</div>}<div className="activity-note"><Info size={15}/><span>{data.data_status==='ok'?'This shows recorded app use. It may miss some activity and does not confirm completed tasks.':'Recording coverage is uncertain. Check the source before drawing conclusions.'}</span></div><details className="chat-source"><summary>View Screenpipe source</summary><p>Original recording overview. Window names and website addresses can sometimes be mismatched.</p><pre>{summary}</pre></details></section>
}

export function ChatResults({results,openWorkflow}:{results:unknown[];openWorkflow:(ref:WorkflowRef)=>void}) {
 return <div className="chat-results">{results.map((raw,i)=>{const r=raw as Result
 if(r.data&&typeof r.data==='object'&&!Array.isArray(r.data)&&'summary' in r.data&&'data_status' in r.data)return <ActivityCard key={i} data={r.data as Record<string,unknown>}/>
 const items=Array.isArray(r.data)?r.data:[r.data]
 return <div key={i}>{r.status&&r.status>=400?<p className="chat-result-error">This action could not be completed. Check the details below.</p>:null}{Array.isArray(r.data)&&!r.data.length&&<p className="chat-no-results">No matching items were returned. This does not mean your recording history is empty.</p>}{items.map((item,j)=>{if(!item||typeof item!=='object')return null;const v=item as {id?:string;title?:string;summary?:string;timestamp?:string;status?:string;reconstruction?:unknown};if(!v.id)return null;const ref:WorkflowRef|null=v.reconstruction?{workflowId:v.id}:v.timestamp?{taskId:v.id}:null;const target=ref?href.workflow(v.id):v.status&&r.operation?.includes('run')?href.run(v.id):null;return <div className="chat-result-card" key={j}><strong>{v.title||'Result'}</strong>{v.timestamp&&<small>{new Date(v.timestamp).toLocaleString()}</small>}{v.summary&&<p>{v.summary}</p>}{v.status&&<small>{v.status.replaceAll('_',' ')}</small>}{target&&<a href={link(target)} onClick={ref?e=>{e.preventDefault();openWorkflow(ref)}:undefined}>Review details <ArrowRight size={14}/></a>}</div>})}</div>})}<details className="chat-diagnostics"><summary>Technical details</summary><pre>{JSON.stringify(results,null,2)}</pre></details></div>
}

export function ActionInputs({value}:{value:unknown}) {
 const labels:Record<string,string>={title:'Name',period:'Time period',instructions:'Instructions',values:'Values to use',missing_values:'Missing information',enabled:'Enabled',timezone:'Time zone',body:'Details',task_id:'Selected task',workflow_id:'Selected workflow',expected_revision:'Version',key:'Selected recording'}
 const rows=(v:unknown,prefix=''):ReactNode[]=>v&&typeof v==='object'&&!Array.isArray(v)?Object.entries(v).flatMap(([k,item])=>rows(item,`${prefix}${labels[k]||k.replaceAll('_',' ')} › `)):[<div className="chat-input-row" key={prefix}><dt>{prefix.replace(/ › $/,'')}</dt><dd>{typeof v==='boolean'?v?'Yes':'No':typeof v==='object'?JSON.stringify(v):String(v??'Not provided')}</dd></div>]
 return <dl className="chat-inputs">{rows(value)}</dl>
}
