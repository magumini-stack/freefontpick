"""미리보기 문구 프리셋 API — '문구 미리보기로 추천 받기'

- GET    /api/preview-phrases       : 노출중인 문구 목록 (sort_order순) — 공개
- POST   /api/preview-phrases       : 문구 생성 — 관리자
- PATCH  /api/preview-phrases/{id}  : 문구 수정 — 관리자
- DELETE /api/preview-phrases/{id}  : 문구 삭제 — 관리자
- POST   /api/preview-phrases/reorder : 순서 일괄 변경 — 관리자
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PreviewPhrase
from ..auth import require_password_changed
from ..schemas import PreviewPhraseCreate, PreviewPhraseUpdate

router = APIRouter(prefix="/api", tags=["preview-phrases"])


def _to_out(p: PreviewPhrase) -> dict:
    return {
        "id": p.id,
        "text": p.text,
        "tags": p.tags or {},
        "is_active": bool(p.is_active),
        "sort_order": p.sort_order,
    }


@router.get("/preview-phrases")
def list_preview_phrases(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> List[dict]:
    """공개 조회는 노출중인 문구만. 어드민 목록 화면은 include_inactive=true로 전체 조회."""
    q = db.query(PreviewPhrase)
    if not include_inactive:
        q = q.filter(PreviewPhrase.is_active.is_(True))
    items = q.order_by(PreviewPhrase.sort_order.asc(), PreviewPhrase.id.asc()).all()
    return [_to_out(p) for p in items]


@router.post("/preview-phrases")
def create_preview_phrase(
    body: PreviewPhraseCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    p = PreviewPhrase(
        text=body.text.strip(),
        tags=body.tags or {},
        is_active=body.is_active,
        sort_order=body.sort_order,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.patch("/preview-phrases/{phrase_id}")
def update_preview_phrase(
    phrase_id: int,
    body: PreviewPhraseUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    p = db.query(PreviewPhrase).filter(PreviewPhrase.id == phrase_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="문구를 찾을 수 없습니다")
    data = body.model_dump(exclude_unset=True)
    if "text" in data and data["text"] is not None:
        p.text = data["text"].strip()
    if "tags" in data and data["tags"] is not None:
        p.tags = data["tags"]
    if "is_active" in data and data["is_active"] is not None:
        p.is_active = data["is_active"]
    if "sort_order" in data and data["sort_order"] is not None:
        p.sort_order = data["sort_order"]
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.delete("/preview-phrases/{phrase_id}")
def delete_preview_phrase(
    phrase_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    p = db.query(PreviewPhrase).filter(PreviewPhrase.id == phrase_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="문구를 찾을 수 없습니다")
    db.delete(p)
    db.commit()
    return {"deleted": phrase_id}


@router.post("/preview-phrases/reorder")
def reorder_preview_phrases(
    order: List[int],
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    """order = [id1, id2, ...] — 배열 순서대로 sort_order를 0부터 재할당."""
    id_to_order = {pid: idx for idx, pid in enumerate(order)}
    items = db.query(PreviewPhrase).filter(PreviewPhrase.id.in_(order)).all()
    for p in items:
        p.sort_order = id_to_order[p.id]
    db.commit()
    return {"updated": len(items)}
