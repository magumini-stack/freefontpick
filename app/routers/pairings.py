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
    return {
        "id": f.id,
        "name": f.name,
        "maker": f.maker or "",
        "stack": f.stack or "'Nanum Gothic',sans-serif",
        "has_file": bool(f.has_file),
        "is_english": bool(f.is_english),
    }


def _to_out(p: FontPairing) -> dict:
    return {
        "id": p.id,
        "theme": p.theme,
        "sample_title": p.sample_title or "",
        "sample_body": p.sample_body or "",
        "description": p.description or "",
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
    """해당 폰트가 제목 또는 본문으로 들어간 조합. 없으면 빈 배열."""
    rows = (
        db.query(FontPairing)
        .filter(or_(
            FontPairing.title_font_id == font_id,
            FontPairing.body_font_id == font_id,
        ))
        .order_by(FontPairing.sort_order, FontPairing.id)
        .all()
    )
    return [_to_out(p) for p in rows]


@router.get("/debug/font-audit")
def font_audit(rebuild: int = 0, db: Session = Depends(get_db)) -> dict:
    """폰트별 서빙 파일 소스 점검 (문제 폰트 전수조사용).

    ?rebuild=1 을 붙이면 해석 캐시를 다시 계산.
    """
    from .files import FONT_AUDIT, FONT_RESOLUTION, build_font_resolution
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
        },
        "problems": problems,
        "all": FONT_AUDIT,
    }
