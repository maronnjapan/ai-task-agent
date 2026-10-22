"""Helpers shared by agent tool sets."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool

from app.utils import dumps


def make_tool(func: Callable[..., Any], name: str, description: str, coroutine: Callable[..., Any] | None = None) -> StructuredTool:
    return StructuredTool.from_function(func=func, coroutine=coroutine, name=name, description=description, infer_schema=True)


def as_json(data: Any) -> str:
    try:
        return dumps(data)
    except (TypeError, ValueError):
        return json.dumps(str(data), ensure_ascii=False)


def task_to_dict(task, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    data = {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "due_at": task.due_at,
        "category_id": task.category_id,
        "category": task.category.name if task.category else None,
        "status": task.status,
        "assignee": task.assignee,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }
    if extra:
        data.update(extra)
    return data


def plan_to_dict(plan, exec_service, include_items: bool = True) -> dict[str, Any]:
    data = {
        "id": plan.id,
        "parent_plan_id": plan.parent_plan_id,
        "objective": plan.objective,
        "acceptance_criteria": plan.acceptance_criteria,
        "status": plan.status,
        "replanning_attempt": plan.replanning_attempt,
        "created_at": plan.created_at,
        "tasks": [
            {"task_id": link.task_id, "acceptance_criteria": link.acceptance_criteria} for link in plan.task_links
        ],
    }
    if include_items:
        deps = exec_service.dependencies(plan.id)
        data["work_items"] = [
            {
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "status": item.status,
                "depends_on": sorted(deps.get(item.id, ())),
                "result": json.loads(item.result) if item.result else None,
            }
            for item in exec_service.list_work_items(plan.id)
        ]
    return data


def memory_to_dict(memory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "scope": memory.scope,
        "kind": memory.kind,
        "confirmed": memory.confirmed,
        "content": memory.content,
        "source": memory.source,
        "task_id": memory.task_id,
        "category_id": memory.category_id,
        "updated_at": memory.updated_at,
    }
