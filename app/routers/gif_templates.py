"""GIF 생성기 템플릿 API.

- GET    /api/gif-templates            노출중인 템플릿 목록 — 공개
- GET    /api/gif-templates/{number}   템플릿 하나 — 공개 (번호 또는 id)
- POST   /api/gif-templates            생성 — 관리자
- PATCH  /api/gif-templates/{id}       수정 — 관리자
- DELETE /api/gif-templates/{id}       삭제 — 관리자
- POST   /api/gif-templates/import     일괄 등록(번호 기준 덮어쓰기) — 관리자
- POST   /api/gif-templates/reorder    순서 변경 — 관리자
- GET    /api/gif-fonts                편집기용 폰트 목록(허브별) — 공개

import 이 있는 이유
-------------------
템플릿 48개를 어드민에서 한 개씩 저장 버튼을 눌러 만들 수는 없다.
제작툴에서 만들어 JSON으로 내보낸 뒤 여기로 한 번에 밀어넣는다.
번호(number)로 덮어쓰기 때문에 같은 파일을 두 번 올려도 중복이 생기지 않는다.

gif-fonts 가 따로 있는 이유
---------------------------
/api/fonts 는 193종을 meta(추천용 8차원 블롭)까지 통째로 준다(~130KB).
편집기에는 이름·굵기·파일 유무만 있으면 되고, 폰트는 허브 6개 안에서만
고르므로 훨씬 작게 줄 수 있다.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AppMeta, Font, FontWeight, GifTemplate, UseCase
from ..auth import require_password_changed

router = APIRouter(prefix="/api", tags=["gif-templates"])

# 편집기 폰트 선택에 노출할 용도 허브. 전체 10개를 다 보여주면
# 목록이 길어지고, GIF로 만들 일이 거의 없는 허브(보고서·UI)가 섞인다.
GIF_HUBS = ["thumbnail", "vlog", "card", "wedding", "quote", "goods"]

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
    sort_order: int = 0


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
    rows = q.order_by(GifTemplate.sort_order.asc(), GifTemplate.id.asc()).all()
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


@router.get("/gif-fonts")
def list_gif_fonts(db: Session = Depends(get_db)) -> dict:
    """편집기 폰트 선택용 — 허브 6개와 그에 속한 폰트만.

    파일이 없는 폰트(has_file=False, 웹폰트도 아님)는 캔버스에 그릴 수 없으니
    아예 내려보내지 않는다. 목록에 떠 있는데 고르면 대체 폰트로 나오는 것이
    가장 나쁘다.
    """
    ucs = {
        uc.slug: uc
        for uc in db.query(UseCase).filter(UseCase.slug.in_(GIF_HUBS)).all()
    }

    # 굵기 파일 목록을 한 번에 모아 폰트별로 나눈다 (폰트마다 조회하면 N+1)
    weights_by_font: Dict[int, List[int]] = {}
    for fw in db.query(FontWeight).order_by(FontWeight.weight).all():
        weights_by_font.setdefault(fw.font_id, []).append(fw.weight)

    def font_out(f: Font) -> dict:
        ws = sorted(set(weights_by_font.get(f.id, []) + [int(f.primary_weight or 400)]))
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

    def usable(f: Font) -> bool:
        return bool(f.has_file) or bool(f.webfont_family)

    hubs = []
    for slug in GIF_HUBS:
        uc = ucs.get(slug)
        if uc is None:
            continue
        seen, fonts = set(), []
        for link in uc.fonts:
            f = link.font
            if f is None or f.id in seen or not usable(f):
                continue
            seen.add(f.id)
            fonts.append(font_out(f))
        hubs.append({
            "slug": uc.slug,
            "title": uc.title,
            "phrases": [p.text for p in uc.phrases],
            "fonts": fonts,
        })
    return {"hubs": hubs}


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
    t = GifTemplate(**body.model_dump())
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


@router.post("/gif-templates/reorder")
def reorder_gif_templates(
    order: List[int],
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    id_to_order = {tid: idx for idx, tid in enumerate(order)}
    rows = db.query(GifTemplate).filter(GifTemplate.id.in_(order)).all()
    for t in rows:
        t.sort_order = id_to_order[t.id]
    _mark_admin_edited(db)
    db.commit()
    return {"updated": len(rows)}
