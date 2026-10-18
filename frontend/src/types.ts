export type Evidence = { call_id: string; quote: string; source_kind: string }
export type Task = { origin?:string; id: string; title: string; timestamp: string; summary: string; evidence: Evidence[]; apps?:string[]; tags?:string[]; confidence?:number|null; end_timestamp?:string|null; source_kind?:string }
export type Workflow = {
  goal: string
  historical_values: Record<string, { value: unknown; evidence: Evidence[] }>
  steps: { description: string; evidence: Evidence[]; source?: 'user' }[]
  missing_values: string[]
  evidence: Evidence[]
}
export type RunReport = {workflow_name:string;workflow_id:string|null;workflow_revision:number|null;started_at:string;finished_at:string|null;final_status:string;summary:string;values_used:Record<string,unknown>|null;instructions:string;actions_attempted:{event_id:string;arguments:Record<string,unknown>}[];actions_completed:{event_id:string;result:unknown}[];verification_results:{event_id:string;result:unknown}[];errors:{event_id:string;message:string;detail:unknown}[];limitations:string[]}
export type Run = {
  report?:RunReport|null; feedback?:{verdict:'looks_good'|'something_wrong';notes:string;reviewed_at:string}|null

  origin?:string; source_kind?:string;
  id: string; task_id: string; title: string; status: string; summary: string
  started_at: string; finished_at: string | null; elapsed_seconds: number | null
  pending_action: { id: string; tool: string; arguments: Record<string, unknown> } | null
  events?: { id: string; timestamp: string; kind: string; title: string; detail: unknown }[]
  workflow_id?: string|null; workflow_revision?:number|null;triggered_by?:string;notify?:boolean
}
export type Health = { status: string; desktop_available: boolean; model_configured: boolean }
export type SavedWorkflow = { definition?:{goal:string;steps:string[]}|null; approved_revision?:number|null;approved_at?:string|null; origin?:string; id: string; title: string; revision: number; task: Task; reconstruction: Workflow; updated_at: string; run_defaults: {values: Record<string,string>; missing_values: Record<string,string>; instructions: string}; user_notes: string; tags:string[] }
export type Schedule = {origin?:string;id:string;workflow_id:string;title:string;frequency:string;local_date:string;local_time:string;timezone:string;enabled:boolean;next_run_at:string|null;workflow_revision:number;notifications:boolean}

// Night Shift (backend/nightshift.py). Times arrive as "HH:MM:SS" and are sent back as "HH:MM".
export type NightSettings = { enabled: boolean; window_start: string; window_end: string; timezone: string; max_tasks_per_night: number; max_actions_per_task: number }
export type NightAnalysis = { at: string; occurrences: number; patterns: number; routine_gaps: number; new_suggestions: number; note: string }
export type NightStatus = { settings: NightSettings; window: { active: boolean; opens_at: string; closes_at: string }; desktop_unlocked: boolean; analysis: NightAnalysis | null; note: string; counts: { suggested: number; approved: number; running: number; unreviewed: number }; limits: string[] }
export type NightProposalStatus = 'suggested' | 'approved' | 'running' | 'done' | 'skipped' | 'missed' | 'reviewed' | 'dismissed' | 'expired'
export type NightEvidence = { id: string; title: string; timestamp: string; app: string; window: string; summary: string }
export type NightScope = { allowed_hosts: string[]; allowed_apps: string[]; may_finalize: boolean; max_actions: number; used: number; window_end: string }
export type NightOutcome = { kind: string; summary: string; actions_attempted: number; actions_completed: number; checks_passed: number; checks_failed: number }
export type NightProposal = {
  origin?: string; plain?: string; id: string; kind: 'missed_next_step' | 'unfinished_work'; apps?: string[]; suggested_scope?: { allowed_hosts: string[]; allowed_apps: string[] }; title: string; rationale: string; confidence: number; status: NightProposalStatus; workflow_id: string | null
  evidence: NightEvidence[]; stats: Record<string, unknown>
  eligibility: { state: 'ready' | 'no_workflow' | 'needs_approval' | 'needs_values' | 'archived'; detail: string }
  scope: NightScope | null; outcome: NightOutcome | null; run_id: string | null; run_status: string | null
  review: { verdict: 'looks_good' | 'something_wrong'; notes: string; reviewed_at?: string } | null; created_at: string; finished_at: string | null
}
export type NightReportItem = {
  origin?: string; plain?: string; id: string; title: string; state: 'completed' | 'prepared' | 'needs_you' | 'failed' | 'skipped' | 'missed'; noticed: string; evidence: NightEvidence[]; did: string; run_id: string | null; workflow_id: string | null
  steps: Omit<NightOutcome, 'kind' | 'summary'>; scope: Omit<NightScope, 'window_end'> | null; needs_attention: boolean; next_step: string; finished_at: string | null
}
export type NightReport = { headline: string; counts: Record<string, number>; items: NightReportItem[] }
