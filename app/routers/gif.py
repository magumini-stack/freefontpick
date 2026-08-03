"""GIF 생성기 페이지 라우트.

- GET /gif            편집기 (단일 페이지)
- GET /gif/templates  템플릿 전체보기 갤러리
- GET /admin/gif      템플릿 제작툴 (관리자용, 검색 제외)

main.py의 catch-all(/{full_path:path})보다 먼저 등록해야 한다.
catch-all이 먼저 잡으면 <!--FFP_HEADER--> 마커가 치환되지 않은
원본 HTML이 그대로 나가 헤더가 사라진다.

템플릿별 페이지(/gif/{번호})를 만들지 않은 이유
---------------------------------------------
편집기는 하나뿐이고 템플릿은 쿼리스트링(?t=017)으로 고른다.
JSON 페이로드만 다른 페이지 48개를 만들면 /design/{id}·/font/{id}에서
이미 겪은 "크롤링됨-색인생성안됨" 판정을 그대로 반복하게 된다.
"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..header import inject_header

router = APIRouter(tags=["gif-page"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = BASE_DIR / "static"


def _page(filename: str, active: str = "gif") -> HTMLResponse:
    html = (STATIC_DIR / filename).read_text(encoding="utf-8")
    return HTMLResponse(inject_header(html, active))


@router.get("/gif", response_class=HTMLResponse)
def gif_editor():
    return _page("gif.html")


@router.get("/gif/templates", response_class=HTMLResponse)
def gif_gallery():
    return _page("gif-templates.html")


@router.get("/admin/gif", response_class=HTMLResponse)
def gif_admin():
    # 제작툴에는 공용 헤더를 넣지 않는다 — 화면을 최대한 넓게 써야 한다
    html = (STATIC_DIR / "admin-gif.html").read_text(encoding="utf-8")
    return HTMLResponse(html)
