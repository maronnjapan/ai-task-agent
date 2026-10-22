from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.schemas.common import Message
from app.schemas.tasks import CategoryCreate, CategoryOut, CategoryUpdate
from app.services.task_service import CategoryService

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(session: Session = Depends(get_session)):
    return [
        CategoryOut(id=c.id, name=c.name, created_at=c.created_at, task_count=n)
        for c, n in CategoryService(session).list()
    ]


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(data: CategoryCreate, session: Session = Depends(get_session)):
    category = CategoryService(session).create(data.name)
    return CategoryOut(id=category.id, name=category.name, created_at=category.created_at)


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(category_id: str, data: CategoryUpdate, session: Session = Depends(get_session)):
    category = CategoryService(session).update(category_id, data.name)
    return CategoryOut(id=category.id, name=category.name, created_at=category.created_at)


@router.delete("/{category_id}", response_model=Message)
def delete_category(category_id: str, session: Session = Depends(get_session)):
    CategoryService(session).delete(category_id)
    return Message(message="deleted")
