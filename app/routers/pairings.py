"""폰트 페어링 API

- GET /api/pairings                 : 전체 페어링 (테마별 정렬) — 공개
- GET /api/fonts/{font_id}/pairings : 특정 폰트가 포함된 페어링 — 공개
- GET /api/pairings/themes          : 전체 테마 이름 목록 — 공개 (어드민 드롭다운용)
- GET /api/pairings/auto-generate   : 메타 기반 자동 조합 추천 (미리보기, 저장 안 함) — 공개
- POST /api/pairings                : 페어링 생성 — 관리자
- PATCH /api/pairings/{id}          : 페어링 수정 — 관리자
- DELETE /api/pairings/{id}         : 페어링 삭제 — 관리자
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Font, FontPairing
from ..auth import require_password_changed
from ..schemas import PairingCreate, PairingUpdate

router = APIRouter(prefix="/api", tags=["pairings"])


def _font_brief(f: Font) -> dict:
    from .files import _merged_weights
    weights = _merged_weights(f)
    return {
        "id": f.id,
        "name": f.name,
        "maker": f.maker or "",
        "stack": f.stack or "'Nanum Gothic',sans-serif",
        "has_file": bool(f.has_file),
        "is_english": bool(f.is_english),
        "available_weights": [w["weight"] for w in weights],
    }


def _to_out(p: FontPairing) -> dict:
    return {
        "id": p.id,
        "theme": p.theme,
        "sample_title": p.sample_title or "",
        "sample_body": p.sample_body or "",
        "description": p.description or "",
        "title_weight": int(getattr(p, "title_weight", 700) or 700),
        "body_weight": int(getattr(p, "body_weight", 400) or 400),
        "sort_order": p.sort_order,
        "title_font": _font_brief(p.title_font),
        "body_font": _font_brief(p.body_font),
    }


@router.get("/pairings")
def list_pairings(db: Session = Depends(get_db)) -> List[dict]:
    rows = (
        db.query(FontPairing)
        .order_by(FontPairing.sort_order, FontPairing.id)
        .all()
    )
    return [_to_out(p) for p in rows]


@router.get("/pairings/themes")
def list_pairing_themes(db: Session = Depends(get_db)) -> List[str]:
    """등록된 페어링 테마 이름 전체 (어드민 드롭다운/자동완성용)."""
    rows = db.query(FontPairing.theme).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


@router.get("/fonts/{font_id}/pairings")
def font_pairings(font_id: int, db: Session = Depends(get_db)) -> List[dict]:
    """해당 폰트가 제목 또는 본문으로 들어간 조합. 없으면 빈 배열.

    프론트엔드가 상위 6개만 잘라 보여주므로, 같은 폰트가 수십 개 조합에
    쓰이는 경우(수트/프리텐다드/나눔스퀘어/노토산스/나눔고딕 등) 항상 옛날
    조합만 노출되고 새로 추가된 굵기 활용 조합(v5, 모던 미니멀 제목/굵은
    산세리프 슬로건/큰 안내 본문)은 뒤로 밀려 절대 안 보이는 문제가 있었다.
    해당 폰트가 이 조합에서 700 이상 굵기로 쓰인 경우를 "굵기 활용 조합"으로
    보고 우선 정렬해 상위 6개 안에 반드시 포함되도록 한다.
    """
    rows = (
        db.query(FontPairing)
        .filter(or_(
            FontPairing.title_font_id == font_id,
            FontPairing.body_font_id == font_id,
        ))
        .order_by(FontPairing.sort_order, FontPairing.id)
        .all()
    )

    def _is_weight_showcase(p: FontPairing) -> bool:
        if p.title_font_id == font_id and (p.title_weight or 0) >= 700:
            return True
        if p.body_font_id == font_id and (p.body_weight or 0) >= 700:
            return True
        return False

    rows.sort(key=lambda p: (0 if _is_weight_showcase(p) else 1, p.sort_order, p.id))
    return [_to_out(p) for p in rows]


@router.get("/debug/font-audit")
def font_audit(rebuild: int = 0, db: Session = Depends(get_db)) -> dict:
    """폰트별 서빙 파일 소스 점검 (문제 폰트 전수조사용).

    ?rebuild=1 을 붙이면 해석 캐시를 다시 계산.
    """
    from .files import FONT_AUDIT, FONT_RESOLUTION, WEIGHT_RESOLUTION, WEIGHT_UNMATCHED, build_font_resolution
    summary = None
    if rebuild or not FONT_AUDIT:
        summary = build_font_resolution(db)
    problems = [e for e in FONT_AUDIT if e["source"] in ("none",) or e.get("note")]
    return {
        "summary": summary or {
            "total": len(FONT_AUDIT),
            "user": sum(1 for e in FONT_AUDIT if e["source"] == "user"),
            "bundled_by_name": sum(1 for e in FONT_AUDIT if e["source"] == "bundled-by-name"),
            "bundled_by_id": sum(1 for e in FONT_AUDIT if e["source"] == "bundled-by-id"),
            "missing": sum(1 for e in FONT_AUDIT if e["source"] == "none"),
            "weight_fonts": len(WEIGHT_RESOLUTION),
            "weight_unmatched": WEIGHT_UNMATCHED,
        },
        "problems": problems,
        "all": FONT_AUDIT,
    }


# ═══════════════════════════════════════════════════════
# 어드민 CRUD — 페어링 관리
# ═══════════════════════════════════════════════════════

def _get_font_or_400(db: Session, font_id: int, label: str) -> Font:
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=400, detail=f"존재하지 않는 {label} 폰트입니다")
    return font


@router.post("/pairings", status_code=status.HTTP_201_CREATED)
def create_pairing(
    payload: PairingCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    _get_font_or_400(db, payload.title_font_id, "제목")
    _get_font_or_400(db, payload.body_font_id, "본문")
    p = FontPairing(
        theme=payload.theme,
        title_font_id=payload.title_font_id,
        body_font_id=payload.body_font_id,
        sample_title=payload.sample_title,
        sample_body=payload.sample_body,
        description=payload.description,
        title_weight=payload.title_weight,
        body_weight=payload.body_weight,
        sort_order=payload.sort_order,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.patch("/pairings/{pairing_id}")
def update_pairing(
    pairing_id: int,
    payload: PairingUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    p = db.query(FontPairing).filter(FontPairing.id == pairing_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="페어링을 찾을 수 없습니다")
    data = payload.model_dump(exclude_unset=True)
    if "title_font_id" in data:
        _get_font_or_400(db, data["title_font_id"], "제목")
    if "body_font_id" in data:
        _get_font_or_400(db, data["body_font_id"], "본문")
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.delete("/pairings/{pairing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pairing(
    pairing_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    p = db.query(FontPairing).filter(FontPairing.id == pairing_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="페어링을 찾을 수 없습니다")
    db.delete(p)
    db.commit()


# ═══════════════════════════════════════════════════════
# 자동 페어링 생성 — 폰트 메타(무드/용도/업종/성격/굵기감/격식/문장길이)
# + 카테고리 태그를 점수화해서 어울리는 상대 폰트를 찾아 3개 이상 추천한다.
# ═══════════════════════════════════════════════════════

_TITLE_USAGE = {"제목", "캐치프레이즈", "로고", "썸네일", "포스터"}
_BODY_USAGE = {"본문", "정보전달", "출판", "UI"}

_THEME_LABELS = {
    "썸네일": "유튜브 썸네일", "제목": "포스터·배너", "포스터": "포스터·배너",
    "캐치프레이즈": "캐치프레이즈", "로고": "로고·BI", "본문": "본문·장문 콘텐츠",
    "정보전달": "본문·장문 콘텐츠", "출판": "출판·에디토리얼", "UI": "UI/UX",
    "SNS카드": "SNS 카드뉴스", "영상자막": "영상 자막", "패키지": "패키지 디자인",
}

_TEMPLATES = {
    "유튜브 썸네일": ("한 달 만에 확 달라졌어요", "전후 비교 영상 지금 공개합니다"),
    "포스터·배너": ("가을 신상 컬렉션", "지금 만나보세요"),
    "캐치프레이즈": ("당신의 이야기를 담다", "브랜드의 첫인상을 결정하는 한 줄"),
    "로고·BI": ("브랜드 이름", "슬로건이 들어갈 자리입니다"),
    "본문·장문 콘텐츠": ("읽기 편한 본문용 조합", "긴 글도 편안하게 읽히는 서체 조합이에요"),
    "출판·에디토리얼": ("이야기의 시작", "한 페이지 한 페이지 정성을 담았습니다"),
    "UI/UX": ("간편하게 시작하세요", "가입부터 결제까지 3분이면 충분해요"),
    "SNS 카드뉴스": ("오늘의 꿀팁 공유", "저장하고 나중에 다시 확인하세요"),
    "영상 자막": ("자막이 잘 보이나요?", "가독성 좋은 자막용 조합입니다"),
    "패키지 디자인": ("정성껏 만들었습니다", "패키지에도 어울리는 조합이에요"),
    "추천 조합": ("어울리는 조합을 찾았어요", "제목과 본문에 함께 써보세요"),
}


def _title_fit(meta: dict) -> float:
    usage = set(meta.get("usage") or [])
    score = 0.0
    if usage & _TITLE_USAGE:
        score += 3
    if meta.get("weight_feel") == "굵음":
        score += 2
    if meta.get("reading_length") == "짧은 글자":
        score += 2
    if usage & _BODY_USAGE:
        score -= 1
    return score


def _body_fit(meta: dict) -> float:
    usage = set(meta.get("usage") or [])
    score = 0.0
    if usage & _BODY_USAGE:
        score += 3
    if meta.get("reading_length") == "장문 가능":
        score += 3
    if meta.get("weight_feel") == "보통":
        score += 1
    if usage & {"제목", "로고", "썸네일"}:
        score -= 1
    return score


def _cohesion(meta_a: dict, meta_b: dict) -> float:
    score = 0.0
    for dim in ("mood", "usage", "industry"):
        a = set(meta_a.get(dim) or [])
        b = set(meta_b.get(dim) or [])
        score += len(a & b)
    fa, fb = meta_a.get("formality"), meta_b.get("formality")
    if fa and fb:
        if fa == fb:
            score += 2
        elif {fa, fb} == {"격식", "캐주얼"}:
            score -= 2
    return score


def _pick_theme(meta_a: dict, meta_b: dict) -> str:
    usage_a = meta_a.get("usage") or []
    usage_b = meta_b.get("usage") or []
    overlap = [u for u in usage_a if u in usage_b]
    for u in overlap + usage_a + usage_b:
        if u in _THEME_LABELS:
            return _THEME_LABELS[u]
    return "추천 조합"


def _pick_weight(font: Font, target: int) -> int:
    """폰트가 실제로 가진 굵기 중 target(700=제목용/400=본문용)에 가장 가까운 값."""
    from .files import _merged_weights
    weights = [w["weight"] for w in _merged_weights(font)]
    if not weights:
        return int(font.primary_weight or target)
    return min(weights, key=lambda w: abs(w - target))


def _describe(title_font: Font, body_font: Font) -> str:
    t_summary = (title_font.meta or {}).get("summary") or f"{title_font.name}"
    return (
        f"{t_summary}는 제목용으로 적합합니다. 여기에 {body_font.name}의 본문용 서체를 "
        f"페어링하면 자연스럽게 읽히는 조합이 됩니다."
    )


@router.get("/pairings/auto-generate")
def auto_generate_pairings(
    font_id: int,
    top_n: int = 5,
    db: Session = Depends(get_db),
) -> List[dict]:
    """anchor 폰트(font_id)를 기준으로, 전체 폰트 중 메타/태그 궁합이 좋은 상대를 찾아
    제목+본문 조합 후보를 점수순으로 반환한다 (저장은 하지 않음 — 미리보기 전용).

    최소 3개 이상을 목표로 하되, 후보 폰트가 3개 미만이면 있는 만큼만 반환한다.
    """
    anchor = db.query(Font).filter(Font.id == font_id).first()
    if not anchor:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    candidates = db.query(Font).filter(Font.id != font_id).all()
    anchor_meta = anchor.meta or {}

    scored = []
    for other in candidates:
        other_meta = other.meta or {}
        cohesion = _cohesion(anchor_meta, other_meta)

        # anchor를 제목으로, other를 본문으로
        score_a_title = _title_fit(anchor_meta) + _body_fit(other_meta) + cohesion
        scored.append((score_a_title, anchor, other))

        # anchor를 본문으로, other를 제목으로
        score_a_body = _title_fit(other_meta) + _body_fit(anchor_meta) + cohesion
        scored.append((score_a_body, other, anchor))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    used_partners = set()
    for score, title_font, body_font in scored:
        partner = body_font.id if title_font.id == anchor.id else title_font.id
        if partner in used_partners:
            continue
        used_partners.add(partner)

        theme = _pick_theme(title_font.meta or {}, body_font.meta or {})
        sample_title, sample_body = _TEMPLATES.get(theme, _TEMPLATES["추천 조합"])
        results.append({
            "theme": theme,
            "title_font_id": title_font.id,
            "title_font_name": title_font.name,
            "body_font_id": body_font.id,
            "body_font_name": body_font.name,
            "title_weight": _pick_weight(title_font, 700),
            "body_weight": _pick_weight(body_font, 400),
            "sample_title": sample_title,
            "sample_body": sample_body,
            "description": _describe(title_font, body_font),
            "score": round(score, 1),
        })
        if len(results) >= top_n:
            break

    return results
