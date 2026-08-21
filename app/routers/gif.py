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


def _tpl_ssr() -> str:
    """템플릿 목록을 서버가 글로 그린다.

    이 페이지의 내용은 템플릿 50개인데 전부 JS 가 그린다. 크롤러가 읽는 본문이
    "불러오는 중…" 뿐이면 광고가 붙은 페이지로서 저가치 콘텐츠로 읽힌다.

    지어낸 글이 아니라 실제 데이터다 — 번호·이름·예시 문구·용도 모두
    app/gif_template_data.py 에 이미 있는 값이고, 화면 갤러리가 보여주는 것과
    같은 목록이다.
    """
    import html as _h

    from ..gif_template_data import GIF_TEMPLATES
    try:
        from ..gif_use_case_data import GIF_USE_CASES
        hubs = {u["slug"]: u.get("title") or u["slug"] for u in GIF_USE_CASES}
    except Exception:
        hubs = {}

    def esc(x):
        return _h.escape(str(x or ""))

    live = [t for t in GIF_TEMPLATES if t.get("is_active", True)]
    live.sort(key=lambda t: t.get("sort_order", 0))

    # 용도별로 묶는다. 50개를 한 줄로 늘어놓으면 읽히지 않는다.
    groups = {}
    for t in live:
        groups.setdefault(t.get("hub_slug", ""), []).append(t)

    out = []
    for slug, items in groups.items():
        rows = "".join(
            '<li><span class="no">%s</span><b>%s</b> — %s</li>'
            % (esc(t.get("number")), esc(t.get("title")), esc(t.get("sample_text")))
            for t in items
        )
        out.append("<h3>%s (%d)</h3><ul>%s</ul>" % (esc(hubs.get(slug, slug)), len(items), rows))

    return (
        '<section class="tplssr" id="tplSsr">'
        "<h2>템플릿 %d종</h2>"
        '<p class="lead">문구·폰트·색을 그대로 두고 내려받아도 되고, 편집기에서 '
        "고쳐 써도 됩니다. 모두 서버에 올리지 않고 브라우저에서 바로 만들어집니다. "
        "아래는 준비된 템플릿과 그 예시 문구입니다.</p>" % len(live)
        + "".join(out)
        + "</section>"
    )


def _page(filename: str, active: str = "gif") -> HTMLResponse:
    html = (STATIC_DIR / filename).read_text(encoding="utf-8")
    return HTMLResponse(inject_header(html, active))


@router.get("/gif", response_class=HTMLResponse)
def gif_editor():
    return _page("gif.html")


@router.get("/gif/templates", response_class=HTMLResponse)
def gif_gallery():
    html = (STATIC_DIR / "gif-templates.html").read_text(encoding="utf-8")
    html = html.replace("{{FFP_GIF_TPL_SSR}}", _tpl_ssr(), 1)
    return HTMLResponse(inject_header(html, "gif"))


@router.get("/admin/gif", response_class=HTMLResponse)
def gif_admin():
    # 제작툴에는 공용 헤더를 넣지 않는다 — 화면을 최대한 넓게 써야 한다
    html = (STATIC_DIR / "admin-gif.html").read_text(encoding="utf-8")
    return HTMLResponse(html)
