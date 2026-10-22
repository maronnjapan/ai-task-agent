from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, id_column, ts_column


class ExecutionPlan(Base):
    __tablename__ = "execution_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned','running','reviewing','passed','failed','blocked','replanned','cancelled')",
            name="ck_execution_plans_status",
        ),
        Index("ix_execution_plans_status", "status"),
    )

    id: Mapped[str] = id_column()
    parent_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="SET NULL"), nullable=True
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="planned")
    replanning_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = ts_column()
    updated_at: Mapped[str] = ts_column()

    task_links: Mapped[list[RelatedPlanToTask]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    work_items: Mapped[list[WorkItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="WorkItem.order_index"
    )
    reviews: Mapped[list[Review]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class RelatedPlanToTask(Base):
    __tablename__ = "related_plan_to_task"
    __table_args__ = (Index("ix_related_plan_to_task_plan", "execution_plan_id"),)

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    execution_plan_id: Mapped[str] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="CASCADE"), primary_key=True
    )
    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan: Mapped[ExecutionPlan] = relationship(back_populates="task_links")


class WorkItem(Base):
    __tablename__ = "work_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed','blocked','skipped')",
            name="ck_work_items_status",
        ),
        Index("ix_work_items_plan", "execution_plan_id"),
    )

    id: Mapped[str] = id_column()
    execution_plan_id: Mapped[str] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON (SPEC 11.4)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = ts_column()
    updated_at: Mapped[str] = ts_column()

    plan: Mapped[ExecutionPlan] = relationship(back_populates="work_items")


class WorkItemDependency(Base):
    __tablename__ = "work_item_dependencies"
    __table_args__ = (
        CheckConstraint("work_item_id <> depends_on_work_item_id", name="ck_work_item_dependencies_self"),
        Index("ix_work_item_dependencies_prereq", "depends_on_work_item_id"),
    )

    work_item_id: Mapped[str] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_work_item_id: Mapped[str] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("agent_type IN ('manager','worker','review')", name="ck_agent_runs_agent_type"),
        CheckConstraint(
            "status IN ('running','succeeded','failed','cancelled')", name="ck_agent_runs_status"
        ),
        Index("ix_agent_runs_plan", "execution_plan_id"),
        Index("ix_agent_runs_started", "started_at"),
        Index("ix_agent_runs_work_item", "work_item_id"),
    )

    id: Mapped[str] = id_column()
    execution_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="SET NULL"), nullable=True
    )
    work_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    agent_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    trigger: Mapped[str | None] = mapped_column(String, nullable=True)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str] = ts_column()
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("status IN ('passed','failed','blocked')", name="ck_reviews_status"),
        Index("ix_reviews_plan", "execution_plan_id"),
    )

    id: Mapped[str] = id_column()
    execution_plan_id: Mapped[str] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = ts_column()

    plan: Mapped[ExecutionPlan] = relationship(back_populates="reviews")
    task_results: Mapped[list[ReviewTaskResult]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )


class ReviewTaskResult(Base):
    __tablename__ = "review_task_results"
    __table_args__ = (
        CheckConstraint("status IN ('passed','failed','blocked')", name="ck_review_task_results_status"),
        Index("ix_review_task_results_task", "task_id"),
    )

    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    review: Mapped[Review] = relationship(back_populates="task_results")
