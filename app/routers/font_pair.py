"""조합 페이지(/font-pair)가 쓰는 API.

얇은 껍데기다 — 고르는 일은 전부 `app/font_pair_engine.py`가 한다.
그 엔진은 저장된 FontPairing을 읽지 않는다(왜인지는 그 파일 첫머리 참조).

2026-08: 용도 3슬롯에서 모양 2슬롯으로 바뀌었다. 파라미터도 category/subtitle
대신 shape/title/body 다. 옛 주소로 들어오는 링크가 있어서 category= 도 함께
받아 shape 로 읽는다 — 모르는 값이면 기본 모양으로 떨어지므로 깨지지 않는다.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..font_pair_engine import generate, score_for
from ..pair_specimens import ALL_SHAPES, DEFAULT_SHAPE

router = APIRouter(prefix="/api/font-pair", tags=["font-pair"])


@router.get("/shapes")
def shapes():
    """모양 칩 목록과 설명 한 줄. 화면이 이름을 따로 갖고 있지 않게 서버가
    준다 — desc 는 칩 아래에 그대로 깔린다."""
    return [{"key": c["key"], "label": c["label"], "desc": c["desc"]}
            for c in ALL_SHAPES]


@router.get("/generate")
def generate_set(
    shape: str = "",
    category: str = "",          # 옛 주소 호환
    script: str = "ko",
    title: int = 0,
    body: int = 0,
    db: Session = Depends(get_db),
):
    """제목 · 본문 두 폰트 한 벌. 0이 아닌 슬롯은 잠근 것으로 본다.

    고른 모양은 제목에 걸린다. 본문은 언제나 고딕·명조에서 고른다 —
    손글씨나 장식체를 문단으로 깔면 읽히지 않기 때문이다.
    """
    out = generate(
        db, shape or category or DEFAULT_SHAPE, script,
        locked={"title": title, "body": body},
    )
    if not out:
        raise HTTPException(status_code=503, detail="조합을 만들지 못했습니다")
    return out


@router.get("/score")
def pair_score_only(title: int, body: int, db: Session = Depends(get_db)):
    """두 폰트의 조합 점수만. 화면에서 위아래를 바꾸거나 폰트를 직접 고르면
    조합을 새로 뽑지 않으므로 이 길로 점수만 다시 받는다."""
    out = score_for(db, title, body)
    if out is None:
        raise HTTPException(status_code=404, detail="폰트를 찾지 못했습니다")
    return out
