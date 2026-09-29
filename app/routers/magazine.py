"""매거진 — /magazine

2026-09-29 부터 매거진은 티스토리 블로그 글을 대표 사진·제목 격자로 모아 거는
곳이다. 글 목록은 어드민 '매거진' 탭에서 관리한다(app/routers/magazine_links.py).

전에 코드로 써 두었던 가이드 글 8편(/magazine/{slug})은 사용자님 지시로 지웠다.
주소가 색인돼 있고 다른 사이트에서 걸었을 수 있어서, 404 대신 /magazine 으로 301.

/about(소개)도 이 라우터에 있다 — 옛 /about.html 이 매거진 첫 글로 옮겨 갔던 인연.
static/magazine.html 의 {{MZ_*}} 마커를 서버가 채워 내보낸다.
"""
import html as _html
import json as _json
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..header import inject_header, not_found_page

router = APIRouter(tags=["magazine"])

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
TEMPLATE_PATH = STATIC_DIR / "magazine.html"
# 사이트 주소는 app/site.py 한 곳에서만 정한다.
from ..site import SITE_URL as BASE_URL

# 지운 가이드 글 주소 → /magazine 으로 301
RETIRED_SLUGS = {
    "font-guide", "by-purpose", "pairing", "license", "glyph-count",
    "webfont", "text-on-photo", "weight-numbers",
}


def _crumbs(*steps) -> dict:
    """빵부스러기 구조화 데이터. (이름, 주소) 를 순서대로 받는다."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": BASE_URL + u}
            for i, (n, u) in enumerate(steps)
        ],
    }


LIST_TITLE = "폰트 매거진 — 무료폰트 소식과 폰트 이야기 | 폰트픽"
LIST_DESC = (
    "폰트픽 블로그에 올린 글을 모았습니다. 무료폰트 소식, 폰트를 고르고 쓰는 방법, "
    "폰트픽 기능 이야기를 대표 사진과 함께 한눈에 봅니다."
)
DEFAULT_OG = f"{BASE_URL}/og-image-v3.png"


def _esc(s) -> str:
    return _html.escape(str(s or ""))


def _render(*, title, desc, canonical, h1, lead, body, json_ld, crumb="",
            og_type="website", og_image=DEFAULT_OG):
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = inject_header(html, "magazine")
    repl = {
        "{{MZ_TITLE}}": _esc(title),
        "{{MZ_DESC}}": _esc(desc),
        "{{MZ_CANONICAL}}": canonical,
        "{{MZ_OGTYPE}}": og_type,
        "{{MZ_OGIMAGE}}": og_image,
        "{{MZ_H1}}": _esc(h1),
        "{{MZ_LEAD}}": _esc(lead),
        "{{MZ_CRUMB}}": crumb,
        "{{MZ_BODY}}": body,
        "{{MZ_JSONLD}}": f'<script type="application/ld+json">{json_ld}</script>',
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    return HTMLResponse(html)


def _link_card(r) -> str:
    """티스토리 글 카드 — 대표 사진 위, 제목 아래. 새 창으로 블로그를 연다."""
    from .magazine_links import _out
    o = _out(r)
    img = (f'<img src="{_esc(o.thumb)}" alt="" loading="lazy" decoding="async">'
           if o.thumb else '<i class="ti ti-article" aria-hidden="true"></i>')
    date = f'<span class="mz-bdate">{_esc(o.published)}</span>' if o.published else ""
    return (
        f'<a class="mz-bcard" href="{_esc(o.url)}" target="_blank" rel="noopener">'
        f'<div class="mz-bthumb">{img}</div>'
        f'<h2>{_esc(o.title)}</h2>{date}</a>'
    )


@router.get("/magazine", response_class=HTMLResponse)
def magazine_list(db: Session = Depends(get_db)):
    from .magazine_links import ordered
    try:
        links = ordered(db)
    except Exception:
        links = []
    if links:
        body = '<div class="mz-grid">' + "".join(_link_card(r) for r in links) + "</div>"
    else:
        body = '<p class="mz-empty">곧 새 글로 찾아오겠습니다.</p>'

    json_ld = _json.dumps([{
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": LIST_TITLE,
        "description": LIST_DESC,
        "url": f"{BASE_URL}/magazine",
        "inLanguage": "ko",
        "isPartOf": {"@type": "WebSite", "name": "폰트픽", "url": BASE_URL},
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": r.title, "url": r.url}
                for i, r in enumerate(links)
            ],
        },
    }, _crumbs(("폰트픽", "/"), ("매거진", "/magazine"))], ensure_ascii=False)

    return _render(
        title=LIST_TITLE, desc=LIST_DESC, canonical=f"{BASE_URL}/magazine",
        h1="폰트 매거진",
        lead="블로그에 올린 글을 모았습니다. 글을 누르면 블로그에서 전체 글을 읽을 수 있습니다.",
        body=body, json_ld=json_ld,
    )


@router.get("/magazine/{slug}", include_in_schema=False)
def magazine_post(slug: str):
    if slug in RETIRED_SLUGS:
        return RedirectResponse(f"{BASE_URL}/magazine", status_code=301)
    return not_found_page()


@router.get("/about", response_class=HTMLResponse)
def about_page(db: Session = Depends(get_db)):
    """소개 — 폰트픽이 어떤 곳이고 누가 만드는지.

    옛 /about.html 은 폰트 고르는 법을 설명하는 긴 글이었고, 그 내용은 매거진
    첫 글로 옮겼다. 이 페이지는 그걸 대신하는 것이 아니라 다른 일을 한다.
    사이트의 정체(무엇을 하는 곳인지·누가 운영하는지·어떻게 확인하는지)를
    한 장으로 밝힌다.

    폰트 종수·글 편수 같은 숫자는 싣지 않는다. 소개는 무엇을 하는 곳인지를
    밝히는 자리이고, 규모를 내세우는 자리가 아니다.
    """
    html = (STATIC_DIR / "about.html").read_text(encoding="utf-8")
    html = inject_header(html, "about")

    json_ld = _json.dumps([{
        "@context": "https://schema.org",
        "@type": "AboutPage",
        "name": "폰트픽 소개",
        "url": f"{BASE_URL}/about",
        "inLanguage": "ko",
        "isPartOf": {"@type": "WebSite", "name": "폰트픽", "url": BASE_URL},
        "mainEntity": {
            "@type": "Organization",
            "name": "(주)와이즈폰트",
            "url": "https://wisefont.co.kr",
            "email": "biz@wisefont.co.kr",
            "telephone": "+82-70-8064-5067",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": "KR",
                "addressLocality": "서울시 영등포구",
                "streetAddress": "당산로16길 9-7",
            },
        },
    }, _crumbs(("폰트픽", "/"), ("소개", "/about"))], ensure_ascii=False)

    html = html.replace(
        "{{AB_JSONLD}}",
        f'<script type="application/ld+json">{json_ld}</script>',
    )
    return HTMLResponse(html)


@router.get("/about.html", include_in_schema=False)
def about_redirect():
    """옛 소개 주소 → 새 소개 주소.

    /about.html 은 오래 색인돼 있었고 404 페이지·푸터에서도 링크하던 주소다.
    성격이 같은 페이지가 /about 으로 남았으므로 그쪽으로 넘긴다.
    (catch-all 정적 서빙보다 이 라우트가 먼저 잡힌다 — 안 그러면 마커가
    안 채워진 about.html 원본이 그대로 나간다.)
    """
    return RedirectResponse(f"{BASE_URL}/about", status_code=301)
