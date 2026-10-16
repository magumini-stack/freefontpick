"""추천 폰트 자판기 — /font-vending (2026-10-16).

사용자님 10/15: "질문 3개, 결과값은 엔진 안에서 매번 달라지게, 다시 뽑기도, 새 페이지로" → 시안 여러 판
(Desktop\\projects\\폰트픽\\맞춤폰트자판기) → 10/16 "이제 올리자". 옛 이름은 '맞춤 폰트 자판기'.

뽑기는 전부 방문자의 브라우저에서 한다. 후보·점수는 시안 폴더의 engine.py → export_pools.py 가 미리 만든
static/vending/data.json(쓰임×느낌 48개 통, 폰트마다 인기 순위)을 페이지가 받아 쓰고, 이 라우트는 템플릿
(static/font-vending.html)에 머리글·바닥글만 끼워 돌려준다 — 폰트 변환(/font-convert)과 같은 방식.
템플릿과 데이터는 시안 폴더의 publish.py 가 갈아 끼운다(이 저장소에서 직접 고치면 다음 publish 때 덮인다).

입구: 메인 제목 아래 [추천 폰트 자판기] 단추(클릭은 track.py 'vending'), 사이트맵(seo.py).
광고: 결과 '오늘의 추천 폰트' 위 가로형 칸 — app/header.py AD_SLOTS['vending_result'].
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..header import inject_header

router = APIRouter(tags=["vending"])

TEMPLATE = Path(__file__).resolve().parent.parent.parent / "static" / "font-vending.html"


@router.get("/font-vending", response_class=HTMLResponse)
def font_vending_page(request: Request, db: Session = Depends(get_db)):
    try:
        from ..font_views import record_page
        record_page(request, "vending", "", db)      # 자판기 열람 (어드민 통계 요약엔 아직 칸이 없다 — page_views 에 쌓인다)
    except Exception:
        pass
    html = TEMPLATE.read_text(encoding="utf-8")
    return HTMLResponse(inject_header(html, "vending"))
