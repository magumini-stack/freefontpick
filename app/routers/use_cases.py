"""용도 허브 조회 API.

- GET /api/use-cases          목록 (홈 "어디에 쓰실 건가요?" 그리드용)
- GET /api/use-cases/{slug}   상세 (추천 4종 + 나머지 목록 + 샘플 문구)

읽기 전용이다. 편집은 /api/admin/use-cases 에서 한다.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import UseCase, Font, Tag
from ..schemas import FontOut
# 폰트 직렬화는 fonts 라우터의 것을 그대로 재사용한다.
# 여기서 따로 만들면 has_pairing·webfont_weights 처리가 갈라져 화면이 어긋난다.
from .fonts import _to_out, _paired_font_ids

router = APIRouter(prefix="/api/use-cases", tags=["use-cases"])


class UseCaseSummary(BaseModel):
    slug: str
    title: str
    subtitle: str
    tag_name: Optional[str] = None
    font_count: int          # 추천 + 태그 폰트 (중복 제외)
    lead_font_id: Optional[int] = None   # 그리드 칸에 대표로 렌더할 폰트


class UseCaseFontOut(BaseModel):
    rank: int
    reason: str
    font: FontOut


# 추천 이유를 단 큰 카드로 노출할 상한. 그 아래 순위는 이름·미리보기만 있는
# 목록으로 내려간다 (이유를 12개 다 쓰면 빈 문장이 늘어 페이지 품질이 떨어진다).
PICK_CARD_LIMIT = 4


class UseCaseDetail(BaseModel):
    slug: str
    title: str
    subtitle: str
    criteria: str
    howto: str
    tag_name: Optional[str] = None
    picks: List[UseCaseFontOut]
    more: List[FontOut]      # 5위 이후 큐레이션 폰트 + 태그 폰트
    phrases: List[str]


def _tag_fonts(db: Session, tag_id: Optional[int]) -> List[Font]:
    if not tag_id:
        return []
    return (
        db.query(Font)
        .join(Font.tags)
        .filter(Tag.id == tag_id)
        .order_by(Font.sort_order, Font.id)
        .all()
    )


@router.get("", response_model=List[UseCaseSummary])
def list_use_cases(db: Session = Depends(get_db)):
    rows = (
        db.query(UseCase)
        .filter(UseCase.is_active.is_(True))
        .order_by(UseCase.sort_order, UseCase.id)
        .all()
    )
    out = []
    for uc in rows:
        pick_ids = [f.font_id for f in uc.fonts]
        tag_ids = [f.id for f in _tag_fonts(db, uc.tag_id)]
        total = len(set(pick_ids) | set(tag_ids))
        out.append(UseCaseSummary(
            slug=uc.slug,
            title=uc.title,
            subtitle=uc.subtitle,
            tag_name=uc.tag.name if uc.tag else None,
            font_count=total,
            lead_font_id=pick_ids[0] if pick_ids else None,
        ))
    return out


@router.get("/{slug}", response_model=UseCaseDetail)
def get_use_case(slug: str, db: Session = Depends(get_db)):
    uc = db.query(UseCase).filter(UseCase.slug == slug).first()
    if not uc or not uc.is_active:
        raise HTTPException(status_code=404, detail="Use case not found")

    paired = _paired_font_ids(db)
    linked = [f for f in uc.fonts if f.font is not None]

    picks = [
        UseCaseFontOut(rank=f.rank, reason=f.reason, font=_to_out(f.font, paired))
        for f in linked[:PICK_CARD_LIMIT]
    ]
    # 5위 이후 큐레이션 폰트가 먼저, 그 뒤에 태그 폰트가 이어진다.
    # 순수 큐레이션 허브(tag_id=None)는 이 앞부분이 목록의 전부다.
    linked_ids = {f.font_id for f in linked}
    more = [_to_out(f.font, paired) for f in linked[PICK_CARD_LIMIT:]]
    more += [
        _to_out(f, paired)
        for f in _tag_fonts(db, uc.tag_id)
        if f.id not in linked_ids
    ]

    return UseCaseDetail(
        slug=uc.slug,
        title=uc.title,
        subtitle=uc.subtitle,
        criteria=uc.criteria,
        howto=uc.howto,
        tag_name=uc.tag.name if uc.tag else None,
        picks=picks,
        more=more,
        phrases=[p.text for p in uc.phrases],
    )
