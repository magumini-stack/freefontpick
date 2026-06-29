"""폰트 CRUD API"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Font, Tag, FontTag
from ..auth import require_password_changed
from ..schemas import FontCreate, FontUpdate, FontOut, FontReorderRequest

router = APIRouter(prefix="/api/fonts", tags=["fonts"])


def _to_out(font: Font) -> FontOut:
    return FontOut(
        id=font.id,
        name=font.name,
        maker=font.maker,
        weights=font.weights or "1종",
        url=font.url or "",
        stack=font.stack or "'Nanum Gothic',sans-serif",
        is_english=bool(font.is_english),
        has_file=bool(font.has_file),
        sort_order=font.sort_order,
        tags=[t.name for t in font.tags],
        meta=font.meta or {},
    )


def _resolve_tags(db: Session, tag_names: list) -> List[Tag]:
    """카테고리 이름 배열 → Tag 객체 배열. 없는 카테고리는 자동 생성."""
    tags = []
    for name in tag_names:
        name = name.strip()
        if not name:
            continue
        tag = db.query(Tag).filter(Tag.name == name).first()
        if not tag:
            max_order = db.query(func.max(Tag.sort_order)).scalar() or 0
            tag = Tag(name=name, sort_order=max_order + 10)
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags


# 공개 API
@router.get("", response_model=List[FontOut])
def list_fonts(db: Session = Depends(get_db)):
    """모든 방문자가 호출. sort_order 순으로 정렬."""
    fonts = db.query(Font).order_by(Font.sort_order, Font.id).all()
    return [_to_out(f) for f in fonts]


@router.get("/{font_id}", response_model=FontOut)
def get_font(font_id: int, db: Session = Depends(get_db)):
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")
    return _to_out(font)


# 관리자 API
@router.post("", response_model=FontOut, status_code=status.HTTP_201_CREATED)
def create_font(
    payload: FontCreate,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    if not payload.tags:
        raise HTTPException(status_code=400, detail="카테고리를 1개 이상 선택해야 합니다")

    # sort_order: 가장 끝으로
    max_order = db.query(func.max(Font.sort_order)).scalar() or 0
    font = Font(
        name=payload.name,
        maker=payload.maker,
        weights=payload.weights,
        url=payload.url or "",
        stack=payload.stack,
        is_english=payload.is_english,
        meta=payload.meta or {},
        sort_order=max_order + 10,
    )
    font.tags = _resolve_tags(db, payload.tags)
    db.add(font)
    db.commit()
    db.refresh(font)
    return _to_out(font)


@router.patch("/{font_id}", response_model=FontOut)
def update_font(
    font_id: int,
    payload: FontUpdate,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    data = payload.model_dump(exclude_unset=True)
    if "tags" in data:
        tag_names = data.pop("tags")
        font.tags = _resolve_tags(db, tag_names)
    for k, v in data.items():
        setattr(font, k, v)
    db.commit()
    db.refresh(font)
    return _to_out(font)


@router.delete("/{font_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_font(
    font_id: int,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")
    db.delete(font)
    db.commit()


@router.post("/reorder", response_model=List[FontOut])
def reorder_fonts(
    payload: FontReorderRequest,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    """폰트 정렬 순서 일괄 변경. items: [{id, sort_order}, ...]"""
    for item in payload.items:
        db.query(Font).filter(Font.id == item.id).update({"sort_order": item.sort_order})
    db.commit()
    fonts = db.query(Font).order_by(Font.sort_order, Font.id).all()
    return [_to_out(f) for f in fonts]
