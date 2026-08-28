"""매거진 — /magazine (목록) + /magazine/{slug} (글)

use_case_route.py 와 같은 방식이다. static/magazine.html 의 {{MZ_*}} 마커를
서버가 채워 완성된 HTML 로 내보낸다. 목록과 글이 템플릿 하나를 함께 쓰는데,
머리말과 본문만 다르고 나머지(헤더·메타·스타일)가 같아서다. 파일을 둘로
나누면 스타일을 두 곳에서 고쳐야 하고, 그러다 한쪽만 고쳐진다.
"""
import html as _html
import json as _json
import re
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..header import inject_header, not_found_page
from ..magazine import POSTS, BY_SLUG, image_src
from ..models import Font, UseCase

router = APIRouter(tags=["magazine"])

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
TEMPLATE_PATH = STATIC_DIR / "magazine.html"
BASE_URL = "https://freefontpick.co.kr"

LIST_TITLE = "폰트 매거진 — 무료폰트 고르는 법과 라이선스 읽는 법 | 폰트픽"
LIST_DESC = (
    "무료 한글 폰트를 고르고 쓰는 데 필요한 것을 정리했습니다. 용도별로 고르는 법, "
    "제목과 본문 조합 만드는 법, 라이선스에서 걸리기 쉬운 조항, 글자 수 때문에 "
    "글자가 깨지는 이유까지 실제 폰트를 재어 본 결과로 씁니다."
)


def _esc(s) -> str:
    return _html.escape(str(s or ""))


def _sorted_posts():
    """최신 글이 위로. 같은 날짜면 목록에 적은 순서를 지킨다."""
    return sorted(POSTS, key=lambda p: p["date"], reverse=True)


def _font_count(db: Session) -> int:
    try:
        return db.query(Font).count()
    except Exception:
        return 0


def _hub_links(db: Session) -> str:
    """본문 {{HUB_LINKS}} 자리에 들어갈 용도 허브 알약.

    허브는 어드민에서 켜고 끄므로 본문에 slug 를 박아 두지 않는다. 박아 두면
    허브를 끈 날 매거진에서 404 로 가는 링크가 남는다.
    """
    try:
        hubs = (
            db.query(UseCase)
            .filter(UseCase.is_active.is_(True))
            .order_by(UseCase.sort_order, UseCase.id)
            .all()
        )
    except Exception:
        hubs = []
    if not hubs:
        return ""
    return '<div class="mz-hubs">' + "".join(
        f'<a href="/use/{_esc(u.slug)}">{_esc(u.title)}</a>' for u in hubs
    ) + "</div>"


def _figure(p) -> str:
    """글 안에 들어가는 그림. 크롤러가 읽는 것은 alt 와 설명글이므로 둘 다 채운다.
    크기를 못 박아 두는 이유는 이미지가 늦게 와도 글이 밀리지 않게 하기 위해서다."""
    im = p.get("image")
    if not im:
        return ""
    return (
        '<figure class="mz-fig">'
        f'<img src="{image_src(p)}" alt="{_esc(im["alt"])}"'
        ' width="1200" height="630" loading="lazy" decoding="async">'
        f'<figcaption>{_esc(im["cap"])}</figcaption>'
        "</figure>"
    )


def _fill(body: str, db: Session) -> str:
    """본문의 런타임 자리표시자를 채운다.

    폰트 종수처럼 바뀌는 값을 글에 박아 두면 폰트를 하나 추가한 날 글이
    틀린 말이 된다. 마커로 두고 여기서 채운다.
    """
    body = body.replace("{{COUNT}}", str(_font_count(db)))
    body = body.replace("{{FIGURE}}", "")   # 글마다 다르므로 여기서는 지우기만
    body = body.replace("{{HUB_LINKS}}", _hub_links(db))
    return body


DEFAULT_OG = f"{BASE_URL}/og-image-v3.png"


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


def _card(p, feat: bool = False) -> str:
    """목록 카드 하나. feat 는 맨 위 글 — 넓은 화면에서 한 줄을 다 쓴다."""
    tags = "".join(f'<span class="mz-tag">{_esc(t)}</span>' for t in p.get("tags", []))
    ico = _esc(p.get("icon") or "ti-article")
    return (
        f'<a class="mz-card{" feat" if feat else ""}" href="/magazine/{p["slug"]}">'
        f'<div class="mz-card-ico"><i class="ti {ico}" aria-hidden="true"></i></div>'
        f'<div class="mz-card-body">'
        f'<h2>{_esc(p["title"])}</h2>'
        f'<p>{_esc(p["lead"])}</p>'
        f'<div class="mz-meta">{tags}<span class="mz-date">{_esc(p["date"])}</span></div>'
        f"</div></a>"
    )


# 글 끝에 붙이는 안내. 글만 읽고 나가는 대신 폰트를 보러 갈 길을 만든다.
POST_CTA = (
    '<div class="mz-cta">'
    "<b>읽었으니, 골라 볼 차례입니다</b>"
    "<span>상업적으로 쓸 수 있는 무료 한글 폰트를 용도별로 모아 두었습니다.</span>"
    '<div class="mz-cta-btns">'
    '<a href="/"><i class="ti ti-typography" aria-hidden="true"></i> 무료폰트 둘러보기</a>'
    '<a class="ghost" href="/font-pair">'
    '<i class="ti ti-arrows-join" aria-hidden="true"></i> 폰트 조합 찾기</a>'
    "</div></div>"
)


@router.get("/magazine", response_class=HTMLResponse)
def magazine_list(db: Session = Depends(get_db)):
    posts = _sorted_posts()
    body = ('<div class="mz-list">'
            + "".join(_card(p, i == 0) for i, p in enumerate(posts))
            + "</div>")

    json_ld = _json.dumps({
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
                {"@type": "ListItem", "position": i + 1, "name": p["title"],
                 "url": f'{BASE_URL}/magazine/{p["slug"]}'}
                for i, p in enumerate(posts)
            ],
        },
    }, ensure_ascii=False)

    return _render(
        title=LIST_TITLE, desc=LIST_DESC, canonical=f"{BASE_URL}/magazine",
        h1="폰트 매거진",
        lead="무료 폰트를 고르고 쓰는 데 필요한 것을 정리했습니다. "
             "폰트픽이 폰트를 하나씩 열어 재어 보면서 알게 된 것들입니다.",
        body=body, json_ld=json_ld,
    )


@router.get("/magazine/{slug}", response_class=HTMLResponse)
def magazine_post(slug: str, db: Session = Depends(get_db)):
    p = BY_SLUG.get(slug)
    if p is None:
        return not_found_page()

    url = f"{BASE_URL}/magazine/{slug}"
    body = '<article class="mz-post">' + _fill(
        p["body"].replace("{{FIGURE}}", _figure(p)), db)

    # 글 아래 다른 글 — 매거진 안에서 돌아다닐 길을 만든다.
    others = [x for x in _sorted_posts() if x["slug"] != slug][:4]
    body += POST_CTA
    if others:
        body += (
            '<nav class="mz-more"><h2>다른 글</h2><ul>'
            + "".join(f'<li><a href="/magazine/{o["slug"]}">{_esc(o["title"])}</a></li>'
                      for o in others)
            + "</ul></nav>"
        )
    body += "</article>"

    src = image_src(p)
    og_image = (BASE_URL + src) if src else DEFAULT_OG

    json_ld = _json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": p["title"],
        "description": p["lead"],
        "url": url,
        "inLanguage": "ko",
        "datePublished": p["date"],
        "dateModified": p["date"],
        "author": {"@type": "Organization", "name": "폰트픽"},
        "publisher": {"@type": "Organization", "name": "폰트픽", "url": BASE_URL},
        "isPartOf": {"@type": "WebSite", "name": "폰트픽", "url": BASE_URL},
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "image": og_image,
    }, ensure_ascii=False)

    crumb = ('<p class="mz-crumb"><a href="/">폰트픽</a> › '
             '<a href="/magazine">매거진</a></p>')

    return _render(
        title=f'{p["title"]} | 폰트픽 매거진',
        desc=p["lead"], canonical=url, h1=p["title"], lead=p["lead"],
        body=body, json_ld=json_ld, crumb=crumb, og_type="article",
        og_image=og_image,
    )


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

    json_ld = _json.dumps({
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
    }, ensure_ascii=False)

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
