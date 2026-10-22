from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_ctx, get_session
from app.context import AppContext
from app.schemas.chats import ChatCreate, ChatOut, DecisionOut, MessageCreate, MessageOut, MessagePage
from app.schemas.common import Message
from app.services.chat_service import ChatService, DecisionService

log = logging.getLogger(__name__)
router = APIRouter(tags=["chats"])


@router.get("/api/tasks/{task_id}/chats", response_model=list[ChatOut])
def list_chats(task_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    rows = ChatService(session, ctx.broker).list_chats(task_id)
    return [
        ChatOut(
            id=c.id,
            task_id=c.task_id,
            title=c.title,
            created_at=c.created_at,
            message_count=n,
            last_message_at=last,
        )
        for c, n, last in rows
    ]


@router.post("/api/tasks/{task_id}/chats", response_model=ChatOut, status_code=201)
def create_chat(
    task_id: str,
    data: ChatCreate | None = None,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    chat = ChatService(session, ctx.broker).create_chat(task_id, data.title if data else None)
    return ChatOut(id=chat.id, task_id=chat.task_id, title=chat.title, created_at=chat.created_at)


@router.delete("/api/chats/{chat_id}", response_model=Message)
def delete_chat(chat_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)):
    ChatService(session, ctx.broker).delete_chat(chat_id)
    return Message(message="deleted")


@router.get("/api/chats/{chat_id}/messages", response_model=MessagePage)
def list_messages(
    chat_id: str,
    before: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    rows, has_more = ChatService(session, ctx.broker).list_messages(chat_id, before=before, limit=limit)
    return MessagePage(
        items=[MessageOut.model_validate(m) for m in rows],
        has_more=has_more,
        next_before=rows[0].id if rows and has_more else None,
    )


@router.post("/api/chats/{chat_id}/messages", response_model=MessageOut, status_code=201)
async def post_message(
    chat_id: str,
    data: MessageCreate,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    message = ChatService(session, ctx.broker).add_message(
        chat_id, data.content, author_type=data.author_type
    )
    session.commit()
    if data.reply and data.author_type == "user":
        asyncio.create_task(_reply(ctx, chat_id))
    return MessageOut.model_validate(message)


async def _reply(ctx: AppContext, chat_id: str) -> None:
    from app.agents.chat_agent import ChatAgent

    ctx.broker.publish("chat.typing", {"chat_id": chat_id, "typing": True})
    try:
        await ChatAgent(ctx).reply(chat_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("chat reply failed")
        with ctx.db.session() as session:
            ChatService(session, ctx.broker).add_message(
                chat_id, f"応答の生成に失敗しました: {exc}", author_type="system"
            )
    finally:
        ctx.broker.publish("chat.typing", {"chat_id": chat_id, "typing": False})


@router.delete("/api/decisions/{decision_id}", response_model=DecisionOut)
def revoke_decision(
    decision_id: str, session: Session = Depends(get_session), ctx: AppContext = Depends(get_ctx)
):
    return DecisionOut.model_validate(DecisionService(session, ctx.broker).revoke(decision_id))
