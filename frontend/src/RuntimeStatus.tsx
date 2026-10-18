import { useEffect, useState } from 'react'
import { api } from './api'
import { Section } from './components'

type Runtime={scheduler_running:boolean;enabled_schedules:number;active_recordings:number;processing_recordings:number;active_runs:number;saved_workflows:number}
export function RuntimeStatus(){
  const [state,setState]=useState<Runtime|null>(null)
  const [error,setError]=useState('')
  useEffect(()=>{let alive=true;const load=()=>api<Runtime>('/system/activity').then(v=>{if(alive){setState(v);setError('')}}).catch(e=>{if(alive)setError(e.message)});void load();const timer=setInterval(()=>void load(),5000);return()=>{alive=false;clearInterval(timer)}},[])
  return <Section title="Workspace activity" subtitle="Live state from this running app.">{error?<p role="alert">{error}</p>:!state?<p role="status">Checking workspace activity…</p>:<dl className="sync-metadata"><dt>Local scheduler</dt><dd>{state.scheduler_running?'Running while the app is open':'Not running'} · {state.enabled_schedules} enabled schedules</dd><dt>Recording segments</dt><dd>{state.active_recordings} active · {state.processing_recordings} processing</dd><dt>Desktop runs</dt><dd>{state.active_runs} active</dd><dt>Saved workflows</dt><dd>{state.saved_workflows}</dd></dl>}</Section>
}
