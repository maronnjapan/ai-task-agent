"""Model -> schema conversions used by several routers."""

from __future__ import annotations

from app.integrations.mcp.config import ConnectionConfig
from app.models import MCPConnection, TaskArtifact, WorkItem
from app.schemas.artifacts import ArtifactOut, ArtifactSourceOut
from app.schemas.execution import ExecutionPlanOut, PlanTaskLinkOut, ReviewOut, ReviewTaskResultOut, WorkItemOut
from app.schemas.integrations import IntegrationOut, ToolPermissionOut
from app.schemas.tasks import TaskOut
from app.services.artifact_service import ArtifactService
from app.services.execution_service import ExecutionService
from app.services.task_service import TaskService
from app.utils import loads


def task_out(service: TaskService, task) -> TaskOut:
    return TaskOut.model_validate({**task.__dict__, **service.decorate(task)})


def artifact_out(service: ArtifactService, artifact: TaskArtifact) -> ArtifactOut:
    return ArtifactOut(
        id=artifact.id,
        task_id=artifact.task_id,
        work_item_id=artifact.work_item_id,
        execution_plan_id=artifact.execution_plan_id,
        title=artifact.title,
        file_path=artifact.file_path,
        absolute_path=service.absolute_path(artifact),
        artifact_type=artifact.artifact_type,
        version=artifact.version,
        status=artifact.status,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
        linked_task_ids=service.linked_task_ids(artifact),
        sources=[ArtifactSourceOut.model_validate(s) for s in artifact.sources],
    )


def plan_out(service: ExecutionService, plan, session) -> ExecutionPlanOut:
    from app.models import Task

    links = []
    for link in plan.task_links:
        task = session.get(Task, link.task_id)
        links.append(PlanTaskLinkOut(task_id=link.task_id, execution_plan_id=link.execution_plan_id, acceptance_criteria=link.acceptance_criteria, task_title=task.title if task else None))
    return ExecutionPlanOut(
        id=plan.id,
        parent_plan_id=plan.parent_plan_id,
        objective=plan.objective,
        acceptance_criteria=plan.acceptance_criteria,
        status=plan.status,
        replanning_attempt=plan.replanning_attempt,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        task_links=links,
        work_item_count=len(service.list_work_items(plan.id)),
    )


def work_item_out(item: WorkItem, deps: dict[str, set[str]]) -> WorkItemOut:
    return WorkItemOut(
        id=item.id,
        execution_plan_id=item.execution_plan_id,
        title=item.title,
        description=item.description,
        status=item.status,
        result=loads(item.result, None),
        order_index=item.order_index,
        retry_count=item.retry_count,
        depends_on=sorted(deps.get(item.id, ())),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def review_out(review) -> ReviewOut:
    return ReviewOut(
        id=review.id,
        execution_plan_id=review.execution_plan_id,
        agent_run_id=review.agent_run_id,
        status=review.status,
        feedback=review.feedback,
        created_at=review.created_at,
        task_results=[ReviewTaskResultOut.model_validate(r) for r in review.task_results],
    )


def integration_out(row: MCPConnection, has_secret: bool, oauth_authorized: bool = False) -> IntegrationOut:
    config = ConnectionConfig.from_model(row)
    return IntegrationOut(
        id=row.id,
        name=row.name,
        adapter=row.adapter,
        transport=row.transport,
        command=row.command,
        args=config.args,
        env=config.env,
        url=row.url,
        headers=config.headers,
        auth_type=row.auth_type,
        auth_config=config.auth_config,
        has_secret=has_secret,
        secret_ref=row.secret_ref,
        timeout_seconds=row.timeout_seconds,
        enabled=row.enabled,
        allowed_tools=config.allowed_tools,
        tool_permissions=[ToolPermissionOut.model_validate(p) for p in row.tool_permissions],
        last_error=row.last_error,
        last_tested_at=row.last_tested_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        oauth_authorized=oauth_authorized,
    )
