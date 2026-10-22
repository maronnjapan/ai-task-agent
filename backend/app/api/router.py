from __future__ import annotations

from fastapi import APIRouter

from app.api import artifacts, categories, chats, execution_plans, integrations, manager, memories, notifications, settings, system, tasks

api_router = APIRouter()
for module in (tasks, categories, chats, manager, execution_plans, artifacts, memories, notifications, integrations, settings, system):
    api_router.include_router(module.router)
