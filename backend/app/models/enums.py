"""Enumerations shared by models, schemas and services."""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW_PENDING = "review_pending"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class Assignee(StrEnum):
    USER = "user"
    AI = "ai"
    SHARED = "shared"


class Actor(StrEnum):
    USER = "user"
    AI = "ai"
    SYSTEM = "system"


class PlanStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    REVIEWING = "reviewing"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    REPLANNED = "replanned"
    CANCELLED = "cancelled"


class WorkItemStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class AgentType(StrEnum):
    MANAGER = "manager"
    WORKER = "worker"
    REVIEW = "review"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    REVIEW_PENDING = "review_pending"
    APPROVED = "approved"
    REVISION_REQUESTED = "revision_requested"


class MemoryScope(StrEnum):
    GLOBAL = "global"
    CATEGORY = "category"
    TASK = "task"


class MemoryKind(StrEnum):
    HYPOTHESIS = "hypothesis"
    AI_INFERENCE = "ai_inference"
    RESEARCH = "research"
    DECISION = "decision"


class DecisionStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


class ContextStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ScheduledActionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"


class NotificationLevel(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class NotificationStatus(StrEnum):
    UNREAD = "unread"
    READ = "read"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ToolPermission(StrEnum):
    READ = "read"
    INTERNAL_WRITE = "internal_write"
    EXTERNAL_WRITE = "external_write"


class AutonomyLevel(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    PROACTIVE = "proactive"


class AppEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
