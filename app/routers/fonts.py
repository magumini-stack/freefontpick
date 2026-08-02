"""폰트 CRUD API"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Font, Tag, FontTag, FontPairing
from ..auth import require_password_changed
from ..schemas import FontCreate, FontUpdate, FontOut, FontReorderRequest
from ..webfont_check import check_webfont, normalize_css_url

router = APIRouter(prefix="/api/fonts", tags=["fonts"])


class WebfontCheckRequest(BaseModel):
    """어드민이 저장 전에 웹폰트 등록값을 미리 검사할 때 쓰는 입력."""
    webfont_family: Optional[str] = None
    webfont_css_url: Optional[str] = None
    webfont_weights: List[int] = Field(default_factory=list)


def _paired_font_ids(db: Session) -> set:
    """페어링에 포함된 폰트 id 집합 (조합추천 뱃지용)"""
    ids = set()
    for (a, b) in db.query(FontPairing.title_font_id, FontPairing.body_font_id).all():
        ids.add(a); ids.add(b)
    return ids


def _parse_webfont_weights(csv: str) -> List[int]:
    if not csv:
        return []
    out = []
    for part in csv.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


# 샘플 이미지 보유 여부는 디스크 인덱스로 판단한다 (DB 컬럼 없음).
# 순환 임포트를 피하려고 함수 안에서 늦게 임포트한다.
def _has_sample(font_id: int) -> bool:
    try:
        from .sample_image import has_sample
        return has_sample(font_id)
    except Exception:
        return False


def _to_out(font: Font, paired_ids: set = frozenset()) -> FontOut:
    return FontOut(
        has_pairing=font.id in paired_ids,
        id=font.id,
        name=font.name,
        maker=font.maker,
        weights=font.weights or "1종",
        url=font.url or "",
        stack=font.stack or "'Nanum Gothic',sans-serif",
        is_english=bool(font.is_english),
        is_pick=bool(font.is_pick),
        primary_weight=int(font.primary_weight or 400),
        webfont_family=font.webfont_family or None,
        webfont_css_url=font.webfont_css_url or None,
        webfont_weights=_parse_webfont_weights(font.webfont_weights),
        has_file=bool(font.has_file),
        sort_order=font.sort_order,
        tags=[t.name for t in font.tags],
        meta=font.meta or {},
        like_count=font.like_count or 0,
        has_sample=_has_sample(font.id),
    )


def _attach_webfont_check(font: Font, out: FontOut) -> FontOut:
    """웹폰트로 등록된 폰트면 저장 직후 실제 CSS를 확인해 경고를 응답에 담는다.

    검증 실패가 저장을 막지는 않는다 — 외부 CDN이 잠깐 죽었다고 폰트 등록 자체가
    불가능해지면 곤란하므로, 어드민에게 알리되 저장은 그대로 진행한다.
    """
    if not (font.webfont_css_url or font.webfont_family):
        return out
    try:
        result = check_webfont(
            font.webfont_family, font.webfont_css_url,
            _parse_webfont_weights(font.webfont_weights),
        )
        out.webfont_errors = result["errors"]
        out.webfont_warnings = result["warnings"]
    except Exception:  # noqa: BLE001
        pass
    return out


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
    paired = _paired_font_ids(db)
    return [_to_out(f, paired) for f in fonts]


# ⚠️ 아래 두 경로는 반드시 `/{font_id}` 보다 먼저 선언해야 한다.
#    FastAPI는 선언 순서대로 매칭하므로, 뒤에 두면 "webfont-audit"을 font_id(int)로
#    파싱하려다 422를 낸다.

@router.post("/webfont-check")
def webfont_check(
    payload: WebfontCheckRequest,
    _admin = Depends(require_password_changed),
) -> dict:
    """저장 전에 웹폰트 등록값이 실제로 동작하는지 검사한다 (DB 변경 없음).

    CSS를 실제로 받아와서 @font-face 존재 여부, font-family 일치, 굵기 제공 여부를
    확인해 errors/warnings로 돌려준다.
    """
    return check_webfont(
        payload.webfont_family, payload.webfont_css_url, payload.webfont_weights,
    )


@router.get("/webfont-audit")
def webfont_audit(
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
) -> dict:
    """웹폰트로 등록된 폰트를 전수 점검한다.

    등록 시점 검증이 없던 때 들어간 잘못된 값을 찾아내기 위한 관리자용 도구.
    """
    rows = (
        db.query(Font)
        .filter(Font.webfont_css_url.isnot(None))
        .order_by(Font.sort_order, Font.id)
        .all()
    )
    items, broken = [], 0
    for f in rows:
        result = check_webfont(
            f.webfont_family, f.webfont_css_url, _parse_webfont_weights(f.webfont_weights),
        )
        if not result["ok"] or result["warnings"]:
            broken += 1
        items.append({
            "id": f.id,
            "name": f.name,
            "webfont_family": f.webfont_family,
            "webfont_css_url": f.webfont_css_url,
            "webfont_weights": _parse_webfont_weights(f.webfont_weights),
            **result,
        })
    return {"checked": len(items), "problem_count": broken, "items": items}


@router.get("/{font_id}", response_model=FontOut)
def get_font(font_id: int, db: Session = Depends(get_db)):
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")
    return _to_out(font, _paired_font_ids(db))


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
        is_pick=payload.is_pick,
        primary_weight=payload.primary_weight or 400,
        webfont_family=(payload.webfont_family or "").strip() or None,
        # @import url("...") 처럼 복사해 붙여넣어도 주소만 뽑아서 저장한다
        webfont_css_url=normalize_css_url(payload.webfont_css_url) or None,
        webfont_weights=",".join(str(w) for w in (payload.webfont_weights or [])) or None,
        meta=payload.meta or {},
        sort_order=max_order + 10,
    )
    font.tags = _resolve_tags(db, payload.tags)
    db.add(font)
    db.commit()
    db.refresh(font)
    return _attach_webfont_check(font, _to_out(font))


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
    if "webfont_weights" in data:
        weights = data.pop("webfont_weights") or []
        font.webfont_weights = ",".join(str(w) for w in weights) or None
    if "webfont_family" in data:
        v = (data.pop("webfont_family") or "").strip()
        font.webfont_family = v or None
    if "webfont_css_url" in data:
        # @import url("...") 처럼 복사해 붙여넣어도 주소만 뽑아서 저장한다
        font.webfont_css_url = normalize_css_url(data.pop("webfont_css_url")) or None
    for k, v in data.items():
        setattr(font, k, v)
    db.commit()
    db.refresh(font)
    return _attach_webfont_check(font, _to_out(font))


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
    paired = _paired_font_ids(db)
    return [_to_out(f, paired) for f in fonts]
