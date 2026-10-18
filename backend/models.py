from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SearchRequest(Model):
    message: str = Field(min_length=1, max_length=4000)
    period: Literal['Today', 'Yesterday', 'This week'] | None = None
    source: Literal['Email', 'Documents', 'Browser'] | None = None

    @field_validator('message')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('message must not be blank')
        return value


class Evidence(Model):
    call_id: str
    quote: str = Field(min_length=1)
    source_kind: Literal['original_activity', 'discussion', 'summary', 'unknown', 'seeded_demo']


class TaskCandidate(Model):
    title: str
    timestamp: datetime
    summary: str
    evidence: list[Evidence] = Field(min_length=1)


class TaskOccurrence(TaskCandidate):
    id: str
    origin: Literal['screenpipe', 'demo'] = 'screenpipe'


class SearchResult(Model):
    tasks: list[TaskCandidate]


class HistoricalValue(Model):
    value: Any
    evidence: list[Evidence] = Field(min_length=1)


class WorkflowStep(Model):
    description: str
    evidence: list[Evidence] = Field(min_length=1)


class Reconstruction(Model):
    goal: str
    historical_values: dict[str, HistoricalValue]
    steps: list[WorkflowStep]
    missing_values: list[str]
    evidence: list[Evidence] = Field(min_length=1)


class ExecutionRequest(Model):
    values: dict[str, str] = Field(default_factory=dict, max_length=100)
    missing_values: dict[str, str] = Field(default_factory=dict, max_length=100)
    instructions: str = Field(default='', max_length=4000)
    # Per-run opt-in: the user waives the per-action approval prompt for this one manual run.
    auto_approve: bool = False

    @field_validator('values', 'missing_values')
    @classmethod
    def bounded_values(cls, values):
        if any(len(k) > 500 or len(v) > 20000 for k, v in values.items()):
            raise ValueError('Value names or content too long')
        return values


class ApprovalRequest(Model):
    action_id: str
    approve: bool


class PendingAction(Model):
    id: str
    tool: Literal['act', 'open_url', 'zavora']
    arguments: dict[str, Any]


class RunEvent(Model):
    id: str
    timestamp: datetime
    kind: str
    title: str
    detail: Any = None


class RunSummary(Model):
    origin: Literal['real', 'demo'] = 'real'
    source_kind: Literal['execution', 'seeded_demo'] = 'execution'
    tags: list[str] = Field(default_factory=list)
    id: str
    task_id: str
    title: str
    status: Literal['running', 'awaiting_approval', 'stopping', 'completed', 'blocked',
                    'failed', 'cancelled', 'interrupted']
    started_at: datetime
    finished_at: datetime | None
    elapsed_seconds: float | None
    summary: str
    pending_action: PendingAction | None
    workflow_id: str | None = None
    workflow_revision: int | None = None
    triggered_by: Literal['manual', 'schedule', 'night'] = 'manual'
    notify: bool = True
    proposal_id: str | None = None


class PDFExport(Model):
    """Metadata for an export already produced by the executor, not a new action."""
    path: str
    filename: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r'^[a-fA-F0-9]{64}$')
    pages: int | None = Field(default=None, ge=1)
    table_labels_verified: list[str] = Field(default_factory=list)
    content_check: str = ''


class RunRecord(RunSummary):
    events: list[RunEvent]
    request: ExecutionRequest
    workflow_snapshot: dict[str, Any] | None = None
    effective_values: dict[str, Any] | None = None
    report: dict[str, Any] | None = None
    feedback: dict[str, Any] | None = None
    scope: dict[str, Any] | None = None
    scope_stop: dict[str, Any] | None = None
    pdf_export: PDFExport | None = None


class RunFeedback(Model):
    verdict: Literal['looks_good', 'something_wrong']
    notes: str = Field(default='', max_length=4000)


class RunReport(Model):
    run_id: str
    workflow_name: str
    workflow_id: str | None = None
    workflow_revision: int | None = None
    started_at: datetime
    finished_at: datetime | None
    final_status: str
    summary: str
    values_used: dict[str, Any] | None
    instructions: str = ''
    actions_attempted: list[dict[str, Any]]
    actions_completed: list[dict[str, Any]]
    verification_results: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    limitations: list[str]
    scope: dict[str, Any] | None = None
    scope_stop: dict[str, Any] | None = None
