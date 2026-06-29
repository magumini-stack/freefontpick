"""카테고리 CRUD API"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Tag, Font
from ..auth import require_password_changed
from ..schemas import TagCreate, TagUpdate, TagOut

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=List[TagOut])
def list_tags(db: Session = Depends(get_db)):
    tags = db.query(Tag).order_by(Tag.sort_order, Tag.id).all()
    return tags


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(
    payload: TagCreate,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    existing = db.query(Tag).filter(Tag.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="이미 같은 이름의 카테고리가 있습니다")
    max_order = db.query(func.max(Tag.sort_order)).scalar() or 0
    tag = Tag(name=payload.name, sort_order=max_order + 10)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.patch("/{tag_id}", response_model=TagOut)
def update_tag(
    tag_id: int,
    payload: TagUpdate,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다")
    if payload.name and payload.name != tag.name:
        dup = db.query(Tag).filter(Tag.name == payload.name, Tag.id != tag_id).first()
        if dup:
            raise HTTPException(status_code=409, detail="이미 같은 이름의 카테고리가 있습니다")
        tag.name = payload.name
    if payload.sort_order is not None:
        tag.sort_order = payload.sort_order
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다")
    # cascade: 연결된 font_tags는 자동 삭제됨 (다대다)
    db.delete(tag)
    db.commit()
