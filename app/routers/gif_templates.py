"""GIF 생성기 템플릿 API.

- GET    /api/gif-templates            노출중인 템플릿 목록 — 공개
- GET    /api/gif-templates/{number}   템플릿 하나 — 공개 (번호 또는 id)
- POST   /api/gif-templates            생성 — 관리자
- PATCH  /api/gif-templates/{id}       수정 — 관리자
- DELETE /api/gif-templates/{id}       삭제 — 관리자
- POST   /api/gif-templates/import     일괄 등록(번호 기준 덮어쓰기) — 관리자
- GET    /api/gif-fonts                편집기용 폰트 목록(용도별) — 공개

- GET    /api/gif-use-cases            용도 5종 + 각 용도의 폰트
- POST   /api/gif-use-cases            용도 추가 — 관리자
- PATCH  /api/gif-use-cases/{id}       이름·노출·순서 — 관리자
- DELETE /api/gif-use-cases/{id}       삭제 — 관리자 (템플릿이 쓰고 있으면 거부)
- PUT    /api/gif-use-cases/{id}/fonts 용도의 폰트 목록 교체 — 관리자

import 이 있는 이유
-------------------
템플릿 50개를 어드민에서 한 개씩 저장 버튼을 눌러 만들 수는 없다.
제작툴에서 만들어 JSON으로 내보낸 뒤 여기로 한 번에 밀어넣는다.
번호(number)로 덮어쓰기 때문에 같은 파일을 두 번 올려도 중복이 생기지 않는다.

gif-fonts 가 따로 있는 이유
---------------------------
/api/fonts 는 193종을 meta(추천용 8차원 블롭)까지 통째로 준다(~130KB).
편집기에는 이름·굵기·파일 유무만 있으면 되고, 폰트는 용도 5종 안에서만
고르므로 훨씬 작게 줄 수 있다.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AppMeta, Font, FontWeight, GifTemplate, GifUseCase, GifUseCaseFont
from ..auth import require_password_changed

router = APIRouter(prefix="/api", tags=["gif-templates"])

# GIF 생성기에서 뺄 폰트.
# 84 조선일보명조체: woff2 파일을 브라우저가 거부한다(Invalid font data).
#   글리프 36,889자 · 압축 해제 시 21.9MB로, 크롬의 폰트 검사기를 통과하지
#   못한다. 목록에 두면 고른 사람에게는 다른 폰트로 그려진 GIF가 나간다.
#   파일을 웹용으로 줄여 다시 올리면 이 줄에서 84를 빼면 된다.
GIF_FONT_EXCLUDE = {84}

# 애니메이션 → 갤러리 필터 분류. static/gif-render.js의 ANIMS와 같은 값이다.
# 여기서 서버가 다시 계산하는 이유: 분류를 클라이언트가 보내주길 기대하면
# 언젠가 빠뜨리고, 그러면 그 템플릿만 '기본' 필터에 잘못 들어가 있는데
# 아무도 눈치채지 못한다.
ANIM_CATEGORY = {
    "typewriter": "basic", "pop": "basic", "wordSwap": "basic", "slideUp": "basic",
    "highlight": "basic", "zoomIn": "basic", "wipe": "basic", "bounceDrop": "basic",
    "neonFlicker": "basic", "flip": "basic",
    "cinematicTrack": "cinematic", "shineSweep": "cinematic",
    "slamImpact": "dynamic", "spinIn": "dynamic", "elasticStretch": "dynamic",
    "shuffleIn": "dynamic", "kickUp": "dynamic", "rollIn": "dynamic",
}


def _to_out(t: GifTemplate) -> dict:
    return {
        "id": t.id,
        "number": t.number,
        "title": t.title or "",
        "hub_slug": t.hub_slug or "",
        "anim": t.anim,
        "anim_category": t.anim_category,
        "effect": t.effect,
        "ratio": t.ratio,
        "gif_rating": t.gif_rating,
        "font_id": t.font_id,
        "font_name": t.font.name if t.font else None,
        "font_weight": t.font_weight,
        # 갤러리 썸네일이 @font-face를 직접 등록해야 해서 폰트 원본 정보까지 함께 준다.
        # 이름만 주면 카드 48장이 전부 대체 폰트로 그려진다.
        "font": {
            "id": t.font.id,
            "name": t.font.name,
            "stack": t.font.stack or "'Nanum Gothic',sans-serif",
            "has_file": bool(t.font.has_file),
            "webfont_family": t.font.webfont_family or None,
            "webfont_css_url": t.font.webfont_css_url or None,
        } if t.font else None,
        "sample_text": t.sample_text or "",
        "config": t.config or {},
        "is_active": bool(t.is_active),
        "sort_order": t.sort_order,
    }


# ══════════════════════════════════════════════════════════════
# 입력 스키마
# ══════════════════════════════════════════════════════════════
def _order_from_number(number: str, fallback: int = 0) -> int:
    """목록 순서는 번호에서 뽑는다.

    따로 관리하던 sort_order를 저장할 때마다 새로 매기던 것이 문제였다.
    '012'를 고쳐 저장하면 목록 맨 뒤로 밀려, 어드민이 방금 고친 템플릿을
    다시 찾아야 했다. 번호가 곧 순서면 어긋날 일이 없다.
    """
    n = (number or "").strip()
    return int(n) * 10 if n.isdigit() else fallback


class GifTemplateIn(BaseModel):
    number: str
    title: str = ""
    hub_slug: str = ""
    anim: str = "typewriter"
    anim_category: str = "basic"
    effect: str = "none"
    ratio: str = "16:9"
    gif_rating: int = 2
    font_id: Optional[int] = None
    font_weight: int = 700
    sample_text: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    # 보내지 않으면 번호에서 뽑는다 (아래 _order_from_number 참고)
    sort_order: Optional[int] = None


class GifTemplatePatch(BaseModel):
    title: Optional[str] = None
    hub_slug: Optional[str] = None
    anim: Optional[str] = None
    anim_category: Optional[str] = None
    effect: Optional[str] = None
    ratio: Optional[str] = None
    gif_rating: Optional[int] = None
    font_id: Optional[int] = None
    font_weight: Optional[int] = None
    sample_text: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


ADMIN_EDITED_KEY = "gif_template_admin_edited"


def _mark_admin_edited(db: Session) -> None:
    """어드민이 템플릿을 손댔다고 표시한다.

    이 표시가 있으면 seed.py의 _seed_gif_templates가 시드를 다시 넣지 않는다.
    시드 버전을 올려 48종을 갈아끼울 때, 운영자가 다듬어 둔 템플릿이
    배포 한 번에 사라지는 걸 막는 유일한 장치다.
    """
    row = db.query(AppMeta).filter(AppMeta.key == ADMIN_EDITED_KEY).first()
    if row is None:
        db.add(AppMeta(key=ADMIN_EDITED_KEY, value="1"))
    elif row.value != "1":
        row.value = "1"


def _sync_from_config(t: GifTemplate) -> None:
    """config 안의 값과 승격 컬럼이 어긋나지 않게 맞춘다.

    제작툴이 보내는 것은 snapshot() 한 덩어리라, 컬럼을 따로 채워달라고
    하면 언젠가 빠뜨린다. 저장 직전에 config에서 다시 읽어 덮어쓴다.
    """
    cfg = t.config or {}
    anim = (cfg.get("animation") or {})
    font = (cfg.get("font") or {})
    canvas = (cfg.get("canvas") or {})
    if anim.get("type"):
        t.anim = anim["type"]
    if cfg.get("effect"):
        t.effect = cfg["effect"]
    if canvas.get("ratio"):
        t.ratio = canvas["ratio"]
    if font.get("id"):
        t.font_id = font["id"]
    if font.get("weight"):
        t.font_weight = int(font["weight"])
    if cfg.get("sampleText") is not None:
        t.sample_text = str(cfg["sampleText"])[:100]
    # 분류는 애니메이션에서 유도한다 — 보내온 값을 믿지 않는다
    t.anim_category = ANIM_CATEGORY.get(t.anim, "basic")


# ══════════════════════════════════════════════════════════════
# 공개 조회
# ══════════════════════════════════════════════════════════════
@router.get("/gif-templates")
def list_gif_templates(
    hub: Optional[str] = None,
    category: Optional[str] = None,
    ratio: Optional[str] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> List[dict]:
    q = db.query(GifTemplate)
    if not include_inactive:
        q = q.filter(GifTemplate.is_active.is_(True))
    if hub:
        q = q.filter(GifTemplate.hub_slug == hub)
    if category and category != "all":
        q = q.filter(GifTemplate.anim_category == category)
    if ratio:
        q = q.filter(GifTemplate.ratio == ratio)
    # 번호순 — number는 '001'처럼 자리를 채운 문자열이라 사전순이 곧 번호순이다
    rows = q.order_by(GifTemplate.number.asc(), GifTemplate.id.asc()).all()
    return [_to_out(t) for t in rows]


@router.get("/gif-templates/{key}")
def get_gif_template(key: str, db: Session = Depends(get_db)) -> dict:
    """번호('017')로도 id로도 찾는다. 공개 URL은 번호를 쓴다."""
    t = db.query(GifTemplate).filter(GifTemplate.number == key).first()
    if t is None and key.isdigit():
        t = db.query(GifTemplate).filter(GifTemplate.id == int(key)).first()
    if t is None:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다")
    return _to_out(t)


def _weights_by_font(db: Session) -> Dict[int, List[int]]:
    """굵기 파일 목록을 한 번에 모아 폰트별로 나눈다 (폰트마다 조회하면 N+1)."""
    out: Dict[int, List[int]] = {}
    for fw in db.query(FontWeight).order_by(FontWeight.weight).all():
        out.setdefault(fw.font_id, []).append(fw.weight)
    return out


def _font_out(f: Font, weights: Dict[int, List[int]]) -> dict:
    ws = sorted(set(weights.get(f.id, []) + [int(f.primary_weight or 400)]))
    return {
        "id": f.id,
        "name": f.name,
        "maker": f.maker or "",
        "stack": f.stack or "'Nanum Gothic',sans-serif",
        "has_file": bool(f.has_file),
        "is_english": bool(f.is_english),
        "primary_weight": int(f.primary_weight or 400),
        "weights": ws,
        "webfont_family": f.webfont_family or None,
        "webfont_css_url": f.webfont_css_url or None,
    }


def _usable(f: Font) -> bool:
    """캔버스에 실제로 그릴 수 있는 폰트인가.

    파일도 웹폰트도 없는 폰트는 목록에 두지 않는다 — 떠 있는데 고르면
    대체 폰트로 그려진 GIF가 나가는 것이 가장 나쁘다.
    """
    if f.id in GIF_FONT_EXCLUDE:
        return False
    return bool(f.has_file) or bool(f.webfont_family)


@router.get("/gif-fonts")
def list_gif_fonts(db: Session = Depends(get_db)) -> dict:
    """편집기 폰트 선택용 — 용도 5종과 그에 속한 폰트.

    응답 키가 'hubs'인 이유는 편집기·갤러리가 이미 그 이름으로 읽고 있어서다.
    안에 담기는 것은 gif_use_cases 테이블의 용도다.
    """
    weights = _weights_by_font(db)
    rows = (db.query(GifUseCase)
              .filter(GifUseCase.is_active.is_(True))
              .order_by(GifUseCase.sort_order, GifUseCase.id).all())
    hubs = []
    for uc in rows:
        fonts, seen = [], set()
        for link in uc.fonts:
            f = link.font
            if f is None or f.id in seen or not _usable(f):
                continue
            seen.add(f.id)
            fonts.append(_font_out(f, weights))
        hubs.append({
            "slug": uc.slug,
            "title": uc.title,
            "subtitle": uc.subtitle or "",
            "fonts": fonts,
        })
    return {"hubs": hubs}


# ══════════════════════════════════════════════════════════════
# 용도 관리 — 어드민
# ══════════════════════════════════════════════════════════════
UC_EDITED_KEY = "gif_use_case_admin_edited"


def _mark_uc_edited(db: Session) -> None:
    """어드민이 용도를 손댔다고 표시한다 — 시드가 덮어쓰지 않게."""
    row = db.query(AppMeta).filter(AppMeta.key == UC_EDITED_KEY).first()
    if row is None:
        db.add(AppMeta(key=UC_EDITED_KEY, value="1"))
    elif row.value != "1":
        row.value = "1"


def _uc_out(uc: GifUseCase, weights: Dict[int, List[int]]) -> dict:
    """어드민용 — 못 쓰는 폰트도 숨기지 않고 이유를 붙여 보여준다.

    공개 API가 조용히 걸러낸 폰트를 어드민에서도 숨기면, 운영자는
    12종을 넣었는데 편집기에 11종만 나오는 이유를 영영 알 수 없다.
    """
    fonts = []
    for link in uc.fonts:
        f = link.font
        if f is None:
            continue
        d = _font_out(f, weights)
        d["usable"] = _usable(f)
        d["blocked_reason"] = (
            "GIF 생성기 제외 목록" if f.id in GIF_FONT_EXCLUDE
            else ("" if (f.has_file or f.webfont_family) else "폰트 파일 없음")
        )
        fonts.append(d)
    return {
        "id": uc.id,
        "slug": uc.slug,
        "title": uc.title,
        "subtitle": uc.subtitle or "",
        "is_active": bool(uc.is_active),
        "sort_order": uc.sort_order,
        "fonts": fonts,
    }


class GifUseCaseIn(BaseModel):
    slug: str
    title: str
    subtitle: str = ""
    is_active: bool = True
    sort_order: int = 0


class GifUseCasePatch(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


@router.get("/gif-use-cases")
def list_gif_use_cases(
    include_inactive: bool = True,
    db: Session = Depends(get_db),
) -> List[dict]:
    q = db.query(GifUseCase)
    if not include_inactive:
        q = q.filter(GifUseCase.is_active.is_(True))
    rows = q.order_by(GifUseCase.sort_order, GifUseCase.id).all()
    weights = _weights_by_font(db)
    return [_uc_out(uc, weights) for uc in rows]


@router.post("/gif-use-cases")
def create_gif_use_case(
    body: GifUseCaseIn,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    if db.query(GifUseCase).filter(GifUseCase.slug == body.slug).first():
        raise HTTPException(status_code=400, detail=f"'{body.slug}'는 이미 있는 용도입니다")
    uc = GifUseCase(**body.model_dump())
    db.add(uc)
    _mark_uc_edited(db)
    db.commit()
    db.refresh(uc)
    return _uc_out(uc, _weights_by_font(db))


@router.patch("/gif-use-cases/{uc_id}")
def update_gif_use_case(
    uc_id: int,
    body: GifUseCasePatch,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    uc = db.query(GifUseCase).filter(GifUseCase.id == uc_id).first()
    if uc is None:
        raise HTTPException(status_code=404, detail="용도를 찾을 수 없습니다")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(uc, k, v)
    _mark_uc_edited(db)
    db.commit()
    db.refresh(uc)
    return _uc_out(uc, _weights_by_font(db))


@router.delete("/gif-use-cases/{uc_id}")
def delete_gif_use_case(
    uc_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    uc = db.query(GifUseCase).filter(GifUseCase.id == uc_id).first()
    if uc is None:
        raise HTTPException(status_code=404, detail="용도를 찾을 수 없습니다")
    used = db.query(GifTemplate).filter(GifTemplate.hub_slug == uc.slug).count()
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"이 용도를 쓰는 템플릿이 {used}개 있습니다. 템플릿을 먼저 옮겨주세요.")
    db.delete(uc)
    _mark_uc_edited(db)
    db.commit()
    return {"deleted": uc_id}


@router.put("/gif-use-cases/{uc_id}/fonts")
def set_gif_use_case_fonts(
    uc_id: int,
    font_ids: List[int],
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    """용도의 폰트 목록을 통째로 바꾼다 — 추가·삭제·순서가 한 번에 끝난다.

    엔드포인트를 셋으로 나누지 않은 이유: 화면에서 폰트 셋을 지우고 둘을
    더한 뒤 저장을 누르면, 나뉘어 있을 때는 요청 다섯 개가 순서대로 성공해야
    한다. 중간에 하나가 실패하면 화면과 DB가 어긋난 채로 남는다.
    """
    uc = db.query(GifUseCase).filter(GifUseCase.id == uc_id).first()
    if uc is None:
        raise HTTPException(status_code=404, detail="용도를 찾을 수 없습니다")

    known = {f.id for f in db.query(Font.id).filter(Font.id.in_(font_ids)).all()}
    ordered, seen = [], set()
    for fid in font_ids:            # 중복은 첫 위치만 남긴다
        if fid in known and fid not in seen:
            seen.add(fid)
            ordered.append(fid)

    db.query(GifUseCaseFont).filter(GifUseCaseFont.gif_use_case_id == uc.id).delete()
    db.flush()
    for rank, fid in enumerate(ordered):
        db.add(GifUseCaseFont(gif_use_case_id=uc.id, font_id=fid, rank=rank))
    _mark_uc_edited(db)
    db.commit()
    db.refresh(uc)
    return _uc_out(uc, _weights_by_font(db))


# ══════════════════════════════════════════════════════════════
# 관리자
# ══════════════════════════════════════════════════════════════
@router.post("/gif-templates")
def create_gif_template(
    body: GifTemplateIn,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    if db.query(GifTemplate).filter(GifTemplate.number == body.number).first():
        raise HTTPException(status_code=400, detail=f"번호 {body.number}는 이미 있습니다")
    data = body.model_dump()
    if data.get("sort_order") is None:
        data["sort_order"] = _order_from_number(body.number)
    t = GifTemplate(**data)
    _sync_from_config(t)
    db.add(t)
    _mark_admin_edited(db)
    db.commit()
    db.refresh(t)
    return _to_out(t)


@router.patch("/gif-templates/{tpl_id}")
def update_gif_template(
    tpl_id: int,
    body: GifTemplatePatch,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    t = db.query(GifTemplate).filter(GifTemplate.id == tpl_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(t, k, v)
    _sync_from_config(t)
    _mark_admin_edited(db)
    db.commit()
    db.refresh(t)
    return _to_out(t)


@router.delete("/gif-templates/{tpl_id}")
def delete_gif_template(
    tpl_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    t = db.query(GifTemplate).filter(GifTemplate.id == tpl_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다")
    db.delete(t)
    _mark_admin_edited(db)
    db.commit()
    return {"deleted": tpl_id}


@router.post("/gif-templates/import")
def import_gif_templates(
    items: List[GifTemplateIn],
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    """번호 기준 덮어쓰기. 같은 파일을 두 번 올려도 중복이 생기지 않는다."""
    created = updated = 0
    for item in items:
        t = db.query(GifTemplate).filter(GifTemplate.number == item.number).first()
        data = item.model_dump()
        # sort_order를 안 보냈으면 번호에서 뽑는다. 고쳐 저장할 때마다 새 순번을
        # 매기면 방금 고친 템플릿이 목록 맨 뒤로 밀려난다.
        if data.get("sort_order") is None:
            data["sort_order"] = _order_from_number(
                item.number, t.sort_order if t else 0)
        if t is None:
            t = GifTemplate(**data)
            _sync_from_config(t)
            db.add(t)
            created += 1
        else:
            for k, v in data.items():
                setattr(t, k, v)
            _sync_from_config(t)
            updated += 1
    _mark_admin_edited(db)
    db.commit()
    return {"created": created, "updated": updated, "total": created + updated}

