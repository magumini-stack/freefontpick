"""공지사항 CRUD API + HTML sanitize"""
import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Notice
from ..auth import require_password_changed
from ..schemas import NoticeCreate, NoticeUpdate, NoticeOut

router = APIRouter(prefix="/api/notices", tags=["notices"])


# 허용 태그: B, STRONG, BR, P, DIV
_ALLOWED_TAG_REGEX = re.compile(
    r"</?(?:b|strong|br|p|div)(?:\s[^>]*)?>", re.IGNORECASE
)
_TAG_REGEX = re.compile(r"<[^>]+>")


def sanitize_html(content: str) -> str:
    """간단한 화이트리스트 sanitizer.

    B/STRONG/BR/P/DIV 외의 모든 태그는 제거. 속성도 모두 제거.
    """
    if not content:
        return ""

    def replace_tag(match):
        tag_str = match.group(0)
        if _ALLOWED_TAG_REGEX.fullmatch(tag_str):
            # 속성 제거: <p class="x"> → <p>, </p> 는 그대로
            inner = tag_str[1:-1].strip()
            if inner.startswith("/"):
                tag_name = inner[1:].strip().split()[0].lower()
                return f"</{tag_name}>"
            tag_name = inner.split()[0].lower()
            return f"<{tag_name}>"
        return ""

    return _TAG_REGEX.sub(replace_tag, content)


@router.get("", response_model=List[NoticeOut])
def list_notices(db: Session = Depends(get_db)):
    # 고정된 공지 우선, 그 다음 최신순
    notices = db.query(Notice).order_by(
        Notice.pinned.desc(),
        Notice.created_at.desc(),
    ).all()
    return notices


@router.get("/{notice_id}", response_model=NoticeOut)
def get_notice(notice_id: int, db: Session = Depends(get_db)):
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    return notice


@router.post("", response_model=NoticeOut, status_code=status.HTTP_201_CREATED)
def create_notice(
    payload: NoticeCreate,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    notice = Notice(
        title=payload.title,
        content=sanitize_html(payload.content),
        pinned=payload.pinned,
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


@router.patch("/{notice_id}", response_model=NoticeOut)
def update_notice(
    notice_id: int,
    payload: NoticeUpdate,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    data = payload.model_dump(exclude_unset=True)
    if "content" in data:
        data["content"] = sanitize_html(data["content"])
    for k, v in data.items():
        setattr(notice, k, v)
    db.commit()
    db.refresh(notice)
    return notice


@router.delete("/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notice(
    notice_id: int,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    db.delete(notice)
    db.commit()
