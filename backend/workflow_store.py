"""Durable workflow snapshots, independent of the search cache."""
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4
from typing import Literal
from .models import Model, TaskOccurrence, Reconstruction, ExecutionRequest, Evidence
from pydantic import Field, field_validator


class WorkflowDefinition(Model):
    """User-authored plan, separate from the original historical reconstruction."""
    goal: str = Field(min_length=1, max_length=4000)
    steps: list[str] = Field(min_length=1, max_length=100)

    @field_validator('goal')
    @classmethod
    def nonblank_goal(cls, value):
        if not value.strip():
            raise ValueError('Add a goal for this workflow.')
        return value.strip()

    @field_validator('steps')
    @classmethod
    def bounded_steps(cls, values):
        if any(not value.strip() or len(value) > 4000 for value in values):
            raise ValueError('Each step must contain between 1 and 4000 characters.')
        return [value.strip() for value in values]


class UserWorkflowStep(Model):
    description: str
    evidence: list[Evidence] = Field(default_factory=list)
    source: Literal['user'] = 'user'


class UserWorkflowPlan(Reconstruction):
    # Empty step evidence is allowed ONLY for the explicitly user-authored plan.
    # Agent-generated Reconstruction retains its original evidence requirements.
    steps: list[UserWorkflowStep]


class SavedWorkflow(Model):
    origin: Literal['real', 'demo'] = 'real'
    source_kind: Literal['historical_workflow', 'seeded_demo'] = 'historical_workflow'
    schema_version: int = 1
    id: str
    title: str = Field(min_length=1, max_length=300)
    revision: int = 1
    created_at: datetime
    updated_at: datetime
    archived: bool = False
    task: TaskOccurrence
    reconstruction: Reconstruction
    ledger: dict
    run_defaults: ExecutionRequest = Field(default_factory=ExecutionRequest)
    user_notes: str = Field(default='', max_length=10000)
    revisions: list[dict] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, max_length=20)
    approved_revision: int | None = None
    approved_at: datetime | None = None
    definition: WorkflowDefinition | None = None

    def execution_plan(self):
        if self.definition is None:
            return self.reconstruction.model_copy(deep=True)
        return UserWorkflowPlan.model_validate({**self.reconstruction.model_dump(),
            'goal': self.definition.goal,
            'steps': [{'description': step, 'source': 'user', 'evidence': []}
                      for step in self.definition.steps]})


class SaveWorkflow(Model):
    task_id: str
    title: str | None = Field(default=None, min_length=1, max_length=300)
    defaults: ExecutionRequest = Field(default_factory=ExecutionRequest)


class UpdateWorkflow(Model):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    run_defaults: ExecutionRequest | None = None
    user_notes: str | None = Field(default=None, max_length=10000)
    tags: list[str] | None = Field(default=None, max_length=20)
    definition: WorkflowDefinition | None = None


class RevisionConflict(ValueError):
    pass


class ApproveWorkflow(Model):
    expected_revision: int = Field(ge=1)


def require_definition_approval(record, request):
    # Historical workflows keep their existing supervised path. Seeded suggestions
    # must first be reviewed as a real saved definition, never as a fake execution.
    if (record.origin == 'demo' or record.definition is not None) and (record.approved_revision != record.revision
            or request.model_copy(update={'auto_approve': False}) != record.run_defaults.model_copy(update={'auto_approve': False})):
        raise ValueError('Save and approve this workflow with these exact values before running it.')


class WorkflowStore:
    def __init__(self, repository):
        self.repository = repository
        self.lock = RLock()
        raw = repository.read('workflows', {})
        self.records = {key: SavedWorkflow.model_validate(value) for key, value in raw.items()}

    def list(self):
        with self.lock:
            return sorted((v.model_copy(deep=True) for v in self.records.values() if not v.archived),
                          key=lambda v: v.updated_at, reverse=True)

    def get(self, key):
        with self.lock:
            record = self.records.get(key)
            if record is None or record.archived:
                raise KeyError(key)
            return record.model_copy(deep=True)

    def commit(self, record):
        # Write before changing memory so disk failures cannot report a successful edit.
        records = {**self.records, record.id: record}
        self.repository.write('workflows', {k: v.model_dump(mode='json') for k, v in records.items()})
        self.records = records
        return record.model_copy(deep=True)

    def create(self, task, reconstruction, ledger, body):
        with self.lock:
            now = datetime.now(timezone.utc)
            return self.commit(SavedWorkflow(id=str(uuid4()), title=body.title or task.title,
                created_at=now, updated_at=now, task=task, reconstruction=reconstruction,
                ledger=ledger, run_defaults=body.defaults,
                origin='demo' if task.origin == 'demo' else 'real',
                source_kind='seeded_demo' if task.origin == 'demo' else 'historical_workflow',
                tags=['demo'] if task.origin == 'demo' else []))

    def update(self, key, body):
        with self.lock:
            record = self.get(key)
            if record.revision != body.expected_revision:
                raise RevisionConflict('Workflow changed. Reload before editing.')
            changes = body.model_dump(exclude={'expected_revision'}, exclude_none=True)
            previous = record.model_dump(mode='json', exclude={'revisions', 'ledger', 'task', 'reconstruction'})
            updated = SavedWorkflow.model_validate({**record.model_dump(), **changes,
                'revision': record.revision + 1, 'updated_at': datetime.now(timezone.utc),
                'approved_revision': None, 'approved_at': None,
                'revisions': [*record.revisions, previous]})
            return self.commit(updated)

    def approve(self, key, expected_revision):
        with self.lock:
            record = self.get(key)
            if record.revision != expected_revision:
                raise RevisionConflict('Workflow changed. Reload and review before approving.')
            if any(not record.run_defaults.missing_values.get(k, '').strip()
                   for k in record.reconstruction.missing_values):
                raise ValueError('Supply and save all missing values before approving.')
            record.approved_revision = record.revision
            record.approved_at = datetime.now(timezone.utc)
            return self.commit(record)

    def archive(self, key):
        with self.lock:
            record = self.get(key)
            record.archived = True
            record.revision += 1
            record.updated_at = datetime.now(timezone.utc)
            self.commit(record)
