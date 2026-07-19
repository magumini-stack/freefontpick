"""디자인 페이지 라우터 — SEO/애드센스용 폰트별 고유 URL

- /design/{font_id}  → 폰트별 title/description/canonical/OG/JSON-LD가 주입된 font.html
                        (2026-07 이관: 텍스트 디자인 모달을 font.html로 옮기면서, 이 경로도
                         index.html이 아닌 font.html을 서빙한다. 클라이언트에서 경로가
                         /design/인 것을 감지해 상세페이지 위에 모달을 자동으로 연다.)
- /font/{font_id}    → 폰트별 title/description/canonical/OG(폰트별 og-image)/JSON-LD가
                        주입된 font.html (2026-07 추가: 상세페이지 SEO 강화)
- /find-font        → 폰트 찾기 게시판 (SEO용 title/description 변경)

실제 콘텐츠는 SPA(index.html/font.html)가 클라이언트에서 렌더한다.
서버는 <head> 메타데이터만 폰트별로 치환해서, 검색엔진이 개별 페이지로 색인하게 한다.
"""
import json as _json
import re
from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Font
from ..header import inject_header

router = APIRouter(tags=["design"])

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
INDEX_PATH = STATIC_DIR / "index.html"
FONT_PAGE_PATH = STATIC_DIR / "font.html"

BASE_URL = "https://freefontpick.co.kr"


def _load_index() -> str:
    """index.html 원본 로드 (매 요청 파일 IO — 트래픽 규모에서 문제 없음)"""
    return INDEX_PATH.read_text(encoding="utf-8")


def _load_font_page() -> str:
    """font.html 원본 로드"""
    return FONT_PAGE_PATH.read_text(encoding="utf-8")


def _inject_crawlable_font_links(html: str, db: Session) -> str:
    """홈페이지 서버 응답에 전체 폰트 상세페이지 링크를 실제 <a href>로 심는다.

    폰트 갤러리는 클라이언트 JS(fetch('/api/fonts') → DOM 삽입)로 그려지기 때문에,
    서버가 최초로 내려주는 HTML에는 카드가 비어있다. 구글봇처럼 JS를 렌더링하는
    크롤러는 문제없지만, 네이버 Yeti 등 JS 렌더링이 제한적인 크롤러는 홈페이지에서
    폰트 링크를 아예 발견하지 못할 수 있다 (sitemap.xml로는 색인되지만, 홈페이지發
    내부링크 효과는 없는 상태).

    이를 보완하기 위해 <noscript> 블록에 전체 폰트로 가는 진짜 <a href="/font/{id}">
    링크 목록을 심는다. <noscript>는 JS를 실행하지 않는 크롤러/브라우저에서만
    렌더링되므로, 일반 사용자 화면(JS 정상 실행)에는 아무 영향이 없다. 다른 라우트
    (design.py의 폰트별 SEO noscript 블록)와 동일한 패턴이다.
    """
    import html as _html_esc

    try:
        rows = db.query(Font.id, Font.name).order_by(Font.id).all()
    except Exception:
        return html

    if not rows:
        return html

    items = "".join(
        f'<li><a href="/font/{fid}">{_html_esc.escape(name or "")}</a></li>'
        for fid, name in rows
    )
    block = (
        '<noscript><nav aria-label="전체 무료폰트 목록">'
        '<h2>전체 무료폰트</h2><ul>' + items + '</ul></nav></noscript>'
    )
    return html.replace("</body>", block + "\n</body>", 1)




def _design_page_meta(font: Font) -> dict:
    """디자인하기 페이지(/design/{id})용 title/description/keywords/url/og_image 생성

    (2026-07 이관: 텍스트 디자인 모달이 font.html로 옮겨가면서, /design/{id}도
     index.html이 아닌 font.html을 서빙한다. font.html은 상세페이지 콘텐츠를
     보여주면서 모달을 자동으로 연다. 그래서 og_image는 상세페이지와 동일한
     og-image.png를 재사용하되, title/description은 '텍스트 디자인' 의도에 맞춘다.)
    """
    name = font.name
    maker = font.maker or ""
    tags = [t.name for t in font.tags] if font.tags else []

    title = f"{name} 텍스트 디자인 만들기 - 무료 PNG 저장 | 폰트픽"
    desc = (
        f"{name}({maker}) 폰트로 예쁜 텍스트 디자인을 만들어보세요. "
        f"외곽선, 그라데이션, 그림자, 네온 등 30여 가지 효과를 적용하고 "
        f"투명배경 PNG로 무료 저장할 수 있습니다."
    )
    keywords = ", ".join(
        [name, f"{name} 다운로드", "텍스트 디자인", "글자 꾸미기"] + tags[:4]
    )
    url = f"{BASE_URL}/design/{font.id}"
    og_image = f"{BASE_URL}/api/fonts/{font.id}/og-image.png"
    return {
        "title": title, "desc": desc, "keywords": keywords,
        "url": url, "og_image": og_image, "name": name, "maker": maker, "tags": tags,
    }


def _replace_meta_for_design(html: str, font: Font) -> str:
    """font.html의 {{FFP_*}} 마커를 '디자인하기' 페이지용 값으로 치환"""
    m = _design_page_meta(font)

    json_ld = _json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": m["title"],
        "description": m["desc"],
        "url": m["url"],
        "inLanguage": "ko",
        "isPartOf": {"@type": "WebSite", "name": "폰트픽", "url": BASE_URL},
        "primaryImageOfPage": {"@type": "ImageObject", "url": m["og_image"], "width": 1200, "height": 630},
        "mainEntity": {
            "@type": "CreativeWork",
            "name": m["name"],
            "creator": {"@type": "Organization", "name": m["maker"]},
            "keywords": ", ".join(m["tags"]),
        },
    }, ensure_ascii=False)
    json_ld_tag = f'<script type="application/ld+json" id="serverJsonLd">{json_ld}</script>'

    html = html.replace("{{FFP_TITLE}}", m["title"])
    html = html.replace("{{FFP_DESC}}", m["desc"])
    html = html.replace("{{FFP_KEYWORDS}}", m["keywords"])
    html = html.replace("{{FFP_CANONICAL}}", m["url"])
    html = html.replace("{{FFP_OG_IMAGE}}", m["og_image"])
    html = html.replace("{{FFP_JSONLD}}", json_ld_tag)

    seo_block = (
        f'<noscript><section><h1>{m["name"]} 텍스트 디자인</h1>'
        f"<p>{m['name']}은(는) {m['maker']}에서 제공하는 무료 폰트입니다. "
        f"폰트픽 텍스트 디자인 도구에서 {m['name']} 폰트에 30여 가지 스타일 효과("
        f"외곽선, 그림자, 네온, 그라데이션 등)를 적용하고, 글자색·자간·줄간격을 "
        f"조절해 투명배경 PNG 이미지로 저장할 수 있습니다. "
        f'관련 태그: {", ".join(m["tags"]) if m["tags"] else "무료폰트"}</p>'
        f'</section></noscript>'
    )
    html = html.replace("</body>", seo_block + "\n</body>", 1)
    return html


@router.get("/design/{font_id}", response_class=HTMLResponse)
def design_page(font_id: int, db: Session = Depends(get_db)):
    """디자인하기 고유 URL — font.html(상세페이지)을 서빙하고, 클라이언트에서
    경로가 /design/인 것을 감지해 텍스트 디자인 모달을 자동으로 연다.
    (2026-07 이관: 예전엔 index.html + 모달이었으나, 모달을 font.html로 옮기면서
     페이지 이동 없이 상세페이지 위에서 바로 모달이 뜨도록 통합했다.)"""
    font = db.query(Font).filter(Font.id == font_id).first()
    if font is None:
        # 폰트 없으면 홈으로 리다이렉트 (soft 404 방지: index를 그냥 주면
        # 검색엔진이 실제 없는 폰트 URL을 계속 재방문할 수 있어 302로 홈 유도)
        return RedirectResponse(url="/", status_code=302)
    html = _load_font_page()
    html = inject_header(html, "")
    return HTMLResponse(_replace_meta_for_design(html, font))


def _font_detail_meta(font: Font) -> dict:
    """폰트 상세페이지(/font/{id})용 title/description/keywords/url/og_image 생성"""
    name = font.name
    maker = font.maker or ""
    tags = [t.name for t in font.tags] if font.tags else []
    intro = ""
    if font.meta and isinstance(font.meta, dict):
        intro = str(font.meta.get("intro") or "").strip()

    title = f"{name} 무료폰트 다운로드 - 어울리는 폰트 조합까지 | 폰트픽"
    desc = intro or (
        f"{name}({maker}) 무료 한글 폰트를 미리 써보고 다운로드하세요. "
        f"상업적 사용 가능, 어울리는 폰트 조합까지 폰트픽에서 한 번에 확인할 수 있습니다."
    )
    keywords = ", ".join(
        [name, f"{name} 다운로드", "무료폰트", "무료 한글 폰트", maker] + tags[:4]
    )
    url = f"{BASE_URL}/font/{font.id}"
    og_image = f"{BASE_URL}/api/fonts/{font.id}/og-image.png"
    return {
        "title": title, "desc": desc, "keywords": keywords,
        "url": url, "og_image": og_image, "name": name, "maker": maker, "tags": tags,
    }


def _replace_meta_for_font_detail(html: str, font: Font) -> str:
    """font.html의 {{FFP_*}} 마커를 폰트별 실제 값으로 치환"""
    m = _font_detail_meta(font)

    json_ld = _json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": m["title"],
        "description": m["desc"],
        "url": m["url"],
        "inLanguage": "ko",
        "isPartOf": {"@type": "WebSite", "name": "폰트픽", "url": BASE_URL},
        "primaryImageOfPage": {"@type": "ImageObject", "url": m["og_image"], "width": 1200, "height": 630},
        "mainEntity": {
            "@type": "CreativeWork",
            "name": m["name"],
            "creator": {"@type": "Organization", "name": m["maker"]},
            "keywords": ", ".join(m["tags"]),
            "image": m["og_image"],
            "license": "https://scripts.sil.org/OFL",
        },
    }, ensure_ascii=False)
    json_ld_tag = f'<script type="application/ld+json" id="serverJsonLd">{json_ld}</script>'

    html = html.replace("{{FFP_TITLE}}", m["title"])
    html = html.replace("{{FFP_DESC}}", m["desc"])
    html = html.replace("{{FFP_KEYWORDS}}", m["keywords"])
    html = html.replace("{{FFP_CANONICAL}}", m["url"])
    html = html.replace("{{FFP_OG_IMAGE}}", m["og_image"])
    html = html.replace("{{FFP_JSONLD}}", json_ld_tag)

    # 크롤러용 noscript 콘텐츠
    seo_block = (
        f'<noscript><section><h1>{m["name"]} 무료폰트</h1>'
        f'<p>{m["name"]}은(는) {m["maker"]}에서 배포하는 무료 한글 폰트입니다. {m["desc"]}</p>'
        f'</section></noscript>'
    )
    html = html.replace("</body>", seo_block + "\n</body>", 1)
    return html


@router.get("/font/{font_id}", response_class=HTMLResponse)
def font_detail_page(font_id: int, db: Session = Depends(get_db)):
    font = db.query(Font).filter(Font.id == font_id).first()
    if font is None:
        return RedirectResponse(url="/", status_code=302)
    html = _load_font_page()
    html = inject_header(html, "")  # 상세페이지는 nav 항목 중 활성 표시할 게 없음
    return HTMLResponse(_replace_meta_for_font_detail(html, font))


@router.get("/", response_class=HTMLResponse)
@router.get("/index.html", response_class=HTMLResponse)
def home_page(db: Session = Depends(get_db)):
    """홈 — 서버가 공유 헤더를 주입해서 응답 (헤더 단일 소스화)

    + 전체 폰트 목록을 <noscript> 링크로 심어서, JS 렌더링이 제한적인
      검색엔진 크롤러도 홈페이지에서 바로 폰트 상세페이지를 발견할 수 있게 한다.
    """
    html = _load_index()
    html = inject_header(html, "home")
    html = _inject_crawlable_font_links(html, db)
    return HTMLResponse(html)


@router.get("/about.html", response_class=HTMLResponse)
def about_page():
    """소개 페이지 — 서버가 공유 헤더를 주입해서 응답"""
    html = (STATIC_DIR / "about.html").read_text(encoding="utf-8")
    return HTMLResponse(inject_header(html, "about"))


@router.get("/faq.html", response_class=HTMLResponse)
def faq_page():
    """자주 묻는 질문 페이지 — 서버가 공유 헤더를 주입해서 응답"""
    html = (STATIC_DIR / "faq.html").read_text(encoding="utf-8")
    return HTMLResponse(inject_header(html, "faq"))


@router.get("/find-font", response_class=HTMLResponse)
def find_font_page():
    """폰트 찾기 게시판 고유 URL — SEO용 title/description 치환"""
    html = _load_index()
    html = inject_header(html, "findfont")
    title = "폰트 찾기 - 이미지로 폰트 이름 찾기 | 폰트픽"
    desc = ("찾고 싶은 폰트 이미지를 올리면 다른 사용자들이 폰트 이름을 답변해드려요. "
            "로그인 없이 무료로 질문하고 답변할 수 있습니다.")
    url = f"{BASE_URL}/find-font"

    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>",
                  html, count=1, flags=re.S)
    html = re.sub(r'(<meta name="description" content=")[^"]*(")',
                  rf"\g<1>{desc}\g<2>", html, count=1)
    html = re.sub(r'(<link rel="canonical" href=")[^"]*(")',
                  rf"\g<1>{url}\g<2>", html, count=1)
    html = re.sub(r'(<meta property="og:title" content=")[^"]*(")',
                  rf"\g<1>{title}\g<2>", html, count=1)
    html = re.sub(r'(<meta property="og:description" content=")[^"]*(")',
                  rf"\g<1>{desc}\g<2>", html, count=1)
    html = re.sub(r'(<meta property="og:url" content=")[^"]*(")',
                  rf"\g<1>{url}\g<2>", html, count=1)
    return HTMLResponse(html)
