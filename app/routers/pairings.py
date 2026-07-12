"""폰트 페어링 공개 API

- GET /api/pairings                 : 전체 페어링 (테마별 정렬)
- GET /api/fonts/{font_id}/pairings : 특정 폰트가 포함된 페어링

어드민 CRUD는 2단계에서 추가.
"""
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Font, FontPairing

router = APIRouter(prefix="/api", tags=["pairings"])


def _font_brief(f: Font) -> dict:
    from .files import WEIGHT_RESOLUTION
    weights = WEIGHT_RESOLUTION.get(f.id, [])
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
