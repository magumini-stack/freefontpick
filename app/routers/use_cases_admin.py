"""용도 허브 어드민 편집 API.

경로를 /api/admin/use-cases 로 분리한 이유:
공개 라우터(/api/use-cases)에는 이미 /{slug} 가 있어서, 같은 prefix 아래에
/admin 같은 고정 경로를 두면 선언 순서에 따라 slug로 먹혀버린다.
fonts.py에서 이미 같은 함정을 겪었으므로(주석 참고) 아예 분리한다.

지원 범위는 '편집'까지다. 허브 생성·삭제는 넣지 않는다 —
허브 구성은 운영 중 수시로 바뀌는 데이터가 아니라 제품 결정이고,
색인된 페이지가 버튼 하나로 사라지면 되돌릴 근거가 남지 않는다.
추가·삭제는 use_case_data.py 수정 + 시드 버전 상향으로 처리한다.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from ..database import get_db
from ..models import UseCase, UseCaseFont, UseCasePhrase, Font, AppMeta
from ..auth import require_password_changed

router = APIRouter(prefix="/api/admin/use-cases", tags=["use-cases-admin"])

# 어드민이 한 번이라도 허브를 편집하면 이 플래그가 켜지고,
# 그 뒤로는 시드가 절대 덮어쓰지 않는다 (seed.py의 _seed_use_cases 참조).
ADMIN_EDITED_KEY = "use_case_admin_edited"


def _mark_admin_edited(db: Session):
    row = db.query(AppMeta).filter(AppMeta.key == ADMIN_EDITED_KEY).first()
    if row is None:
        db.add(AppMeta(key=ADMIN_EDITED_KEY, value="1"))
    elif row.value != "1":
        row.value = "1"


class PickIn(BaseModel):
    font_id: int
    reason: str = Field(default="", max_length=500)


class UseCasePatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=60)
    subtitle: Optional[str] = Field(default=None, max_length=120)
    criteria: Optional[str] = None
    howto: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class ReorderItem(BaseModel):
    id: int
    sort_order: int


class PickOut(BaseModel):
    font_id: int
    font_name: str
    rank: int
    reason: str


class UseCaseAdminOut(BaseModel):
    id: int
    slug: str
    title: str
    subtitle: str
    criteria: str
    howto: str
    is_active: bool
    sort_order: int
    tag_name: Optional[str] = None
    picks: List[PickOut]
    phrases: List[str]


def _to_out(uc: UseCase) -> UseCaseAdminOut:
    return UseCaseAdminOut(
        id=uc.id,
        slug=uc.slug,
        title=uc.title,
        subtitle=uc.subtitle or "",
        criteria=uc.criteria or "",
        howto=uc.howto or "",
        is_active=bool(uc.is_active),
        sort_order=uc.sort_order,
        tag_name=uc.tag.name if uc.tag else None,
        picks=[
            PickOut(
                font_id=p.font_id,
                font_name=p.font.name if p.font else f"(삭제된 폰트 #{p.font_id})",
                rank=p.rank,
                reason=p.reason or "",
            )
            for p in uc.fonts
        ],
        phrases=[ph.text for ph in uc.phrases],
    )


def _get(db: Session, use_case_id: int) -> UseCase:
    uc = db.query(UseCase).filter(UseCase.id == use_case_id).first()
    if uc is None:
        raise HTTPException(status_code=404, detail="용도 허브를 찾을 수 없습니다")
    return uc


@router.get("", response_model=List[UseCaseAdminOut])
def list_all(db: Session = Depends(get_db), _admin=Depends(require_password_changed)):
    """비활성 허브까지 전부 반환 (어드민 목록용)."""
    rows = db.query(UseCase).order_by(UseCase.sort_order, UseCase.id).all()
    return [_to_out(uc) for uc in rows]


@router.patch("/{use_case_id}", response_model=UseCaseAdminOut)
def update_use_case(
    use_case_id: int,
    payload: UseCasePatch,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    uc = _get(db, use_case_id)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(uc, k, v)
    _mark_admin_edited(db)
    db.commit()
    db.refresh(uc)
    return _to_out(uc)


@router.put("/{use_case_id}/fonts", response_model=UseCaseAdminOut)
def replace_picks(
    use_case_id: int,
    picks: List[PickIn],
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    """추천 폰트를 통째로 교체한다 (배열 순서가 곧 rank).

    행 단위 CRUD 대신 일괄 교체를 쓰는 이유: 순서를 바꾸는 편집이 잦은데,
    개별 rank를 주고받으면 중간에 실패했을 때 순서가 어긋난 채로 남는다.
    """
    uc = _get(db, use_case_id)

    if len(picks) > 12:
        raise HTTPException(status_code=400, detail="추천 폰트는 최대 12개까지입니다")

    seen = set()
    for p in picks:
        if p.font_id in seen:
            raise HTTPException(status_code=400, detail="같은 폰트를 중복으로 넣을 수 없습니다")
        seen.add(p.font_id)

    if seen:
        found = {fid for (fid,) in db.query(Font.id).filter(Font.id.in_(seen)).all()}
        missing = seen - found
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"존재하지 않는 폰트입니다: {sorted(missing)}",
            )

    db.query(UseCaseFont).filter(UseCaseFont.use_case_id == uc.id).delete()
    for i, p in enumerate(picks, start=1):
        db.add(UseCaseFont(
            use_case_id=uc.id, font_id=p.font_id, rank=i, reason=p.reason or "",
        ))
    _mark_admin_edited(db)
    db.commit()
    db.refresh(uc)
    return _to_out(uc)


@router.put("/{use_case_id}/phrases", response_model=UseCaseAdminOut)
def replace_phrases(
    use_case_id: int,
    phrases: List[str],
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    uc = _get(db, use_case_id)
    cleaned = [t.strip() for t in phrases if t and t.strip()]
    if len(cleaned) > 10:
        raise HTTPException(status_code=400, detail="문구는 최대 10개까지입니다")
    for t in cleaned:
        if len(t) > 100:
            raise HTTPException(status_code=400, detail="문구는 100자를 넘을 수 없습니다")

    db.query(UseCasePhrase).filter(UseCasePhrase.use_case_id == uc.id).delete()
    for i, t in enumerate(cleaned):
        db.add(UseCasePhrase(use_case_id=uc.id, text=t, sort_order=(i + 1) * 10))
    _mark_admin_edited(db)
    db.commit()
    db.refresh(uc)
    return _to_out(uc)


@router.post("/reorder", response_model=List[UseCaseAdminOut])
def reorder(
    items: List[ReorderItem],
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    by_id = {uc.id: uc for uc in db.query(UseCase).all()}
    for it in items:
        uc = by_id.get(it.id)
        if uc is not None:
            uc.sort_order = it.sort_order
    _mark_admin_edited(db)
    db.commit()
    rows = db.query(UseCase).order_by(UseCase.sort_order, UseCase.id).all()
    return [_to_out(uc) for uc in rows]
