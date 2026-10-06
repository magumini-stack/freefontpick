"""폰트 변환 — /font-convert (2026-10-06).

사용자님: "브라우저에서 폰트 변환하는 서비스를 만들어보고 싶어. 시안 만들어봐" → 시안
(Desktop\\projects\\폰트픽\\폰트변환_시안) → "Adobe KR-9 2,780자, TTF->OTF·OTF->TTF 도" → "폰트픽 사이트에 붙이자".

변환은 전부 방문자의 브라우저에서 한다(static/font-convert.html 의 웹 워커). 이 서버는 페이지만
내주고 폰트 파일은 받지도 보내지도 않는다 — 큰 한글 폰트를 서버에서 압축하면 감당이 안 된다.
그래서 이 라우트는 템플릿에 머리글·바닥글만 끼워 돌려준다. 주소(canonical·JSON-LD)는 템플릿의
{{FFP_ORIGIN}} 을 inject_header 가 채운다.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..header import inject_header

router = APIRouter(tags=["convert"])

TEMPLATE = Path(__file__).resolve().parent.parent.parent / "static" / "font-convert.html"


@router.get("/font-convert", response_class=HTMLResponse)
def font_convert_page(request: Request, db: Session = Depends(get_db)):
    try:
        from ..font_views import record_page
        record_page(request, "convert", "", db)      # 어드민 '통계' 요약의 '폰트 변환 열람'
    except Exception:
        pass
    html = TEMPLATE.read_text(encoding="utf-8")
    return HTMLResponse(inject_header(html, "convert"))
