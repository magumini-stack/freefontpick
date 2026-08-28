"""조합 페이지(/font-pair)가 쓰는 API.

얇은 껍데기다 — 고르는 일은 전부 `app/font_pair_engine.py`가 한다.
그 엔진은 저장된 FontPairing을 읽지 않는다(왜인지는 그 파일 첫머리 참조).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..font_pair_engine import generate
from ..pair_specimens import PAIR_CATEGORIES, DEFAULT_CATEGORY

router = APIRouter(prefix="/api/font-pair", tags=["font-pair"])


@router.get("/categories")
def categories():
    """카테고리 칩 목록과 설명 한 줄. 화면이 이름을 따로 갖고 있지 않게
    서버가 준다 — desc는 칩 아래에 그대로 깔린다."""
    return [{"key": c["key"], "label": c["label"], "mockup": c["mockup"],
             "desc": c["desc"]}
            for c in PAIR_CATEGORIES]


@router.get("/generate")
def generate_set(
    category: str = DEFAULT_CATEGORY,
    script: str = "ko",
    title: int = 0,
    subtitle: int = 0,
    body: int = 0,
    borrow: str = "",
    db: Session = Depends(get_db),
):
    """타이틀·서브타이틀·본문 한 벌. 0이 아닌 슬롯은 잠근 것으로 본다.

    자리마다 두 슬롯은 같은 폰트의 다른 굵기로 묶여 나온다(font_pair_engine의
    FAMILY_PAIRS). 응답의 family에 어느 두 슬롯인지 담긴다.

    borrow는 '뜻밖의 발견'이 어느 카테고리의 틀을 빌릴지 지정한다 —
    주소로 같은 화면을 재현하려면 그것까지 있어야 한다.
    """
    out = generate(
        db, category, script,
        locked={"title": title, "subtitle": subtitle, "body": body},
        borrow=borrow,
    )
    if not out:
        raise HTTPException(status_code=503, detail="조합을 만들지 못했습니다")
    return out
