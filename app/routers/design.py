"""디자인 페이지 라우터 — SEO/애드센스용 폰트별 고유 URL

- /design/{font_id}  → 폰트별 title/description/canonical/OG/JSON-LD가 주입된 index.html
- /font/{font_id}    → 폰트별 title/description/canonical/OG(폰트별 og-image)/JSON-LD가
                        주입된 font.html (2026-07 추가: 상세페이지 SEO 강화)
- /find-font        → 폰트 찾기 게시판 (SEO용 title/description 변경)

세 라우트 모두 실제 콘텐츠는 SPA(index.html/font.html)가 클라이언트에서 렌더한다.
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


def _replace_meta_for_font(html: str, font: Font) -> str:
    """폰트별 head 메타데이터 치환"""
    name = font.name
    maker = font.maker or ""
    tags = [t.name for t in font.tags] if font.tags else []

    title = f"{name} 텍스트 디자인 만들기 - 무료 PNG 저장 | 폰트픽"
    desc = (
        f"{name}({maker}) 폰트로 예쁜 텍스트 디자인을 만들어보세요. "
        f"외곽선, 그라데이션, 그림자, 네온 등 30여 가지 효과를 적용하고 "
        f"투명배경 PNG로 무료 저장할 수 있습니다."
    )
    url = f"{BASE_URL}/design/{font.id}"

    # <title>
    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>",
                  html, count=1, flags=re.S)
    # description
    html = re.sub(r'(<meta name="description" content=")[^"]*(")',
                  rf"\g<1>{desc}\g<2>", html, count=1)
    # keywords 확장
    kw_extra = ", ".join(
        [name, f"{name} 다운로드", "텍스트 디자인", "글자 꾸미기"] + tags[:4]
    )
    html = re.sub(r'(<meta name="keywords" content=")([^"]*)(")',
                  rf"\g<1>\g<2>, {kw_extra}\g<3>", html, count=1)
    # canonical
    html = re.sub(r'(<link rel="canonical" href=")[^"]*(")',
                  rf"\g<1>{url}\g<2>", html, count=1)
    # OG
    html = re.sub(r'(<meta property="og:title" content=")[^"]*(")',
                  rf"\g<1>{title}\g<2>", html, count=1)
    html = re.sub(r'(<meta property="og:description" content=")[^"]*(")',
                  rf"\g<1>{desc}\g<2>", html, count=1)
    html = re.sub(r'(<meta property="og:url" content=")[^"]*(")',
                  rf"\g<1>{url}\g<2>", html, count=1)

    # JSON-LD 구조화 데이터 (프론트에서 동적으로 넣는 것과 별개로,
    # JS 실행 안 하는 크롤러를 위해 서버에서도 심어둠)
    json_ld = _json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": f"{name} 텍스트 디자인 만들기",
        "description": desc,
        "url": url,
        "inLanguage": "ko",
        "isPartOf": {"@type": "WebSite", "name": "폰트픽", "url": BASE_URL},
        "mainEntity": {
            "@type": "CreativeWork",
            "name": name,
            "creator": {"@type": "Organization", "name": maker},
            "keywords": ", ".join(tags),
        },
    }, ensure_ascii=False)
    html = html.replace(
        "</head>",
        f'<script type="application/ld+json" id="serverJsonLd">{json_ld}</script>\n</head>',
        1,
    )

    # 크롤러용 noscript 콘텐츠 — 중복/얇은 콘텐츠 방지의 핵심
    seo_block = (
        f'<noscript><section><h1>{name} 텍스트 디자인</h1>'
        f"<p>{name}은(는) {maker}에서 제공하는 무료 폰트입니다. "
        f"폰트픽 텍스트 디자인 도구에서 {name} 폰트에 30여 가지 스타일 효과("
        f"외곽선, 그림자, 네온, 그라데이션 등)를 적용하고, 글자색·자간·줄간격을 "
        f"조절해 투명배경 PNG 이미지로 저장할 수 있습니다. "
        f'관련 태그: {", ".join(tags) if tags else "무료폰트"}</p>'
        f'</section></noscript>'
    )
    html = html.replace("</body>", seo_block + "\n</body>", 1)
    return html


@router.get("/design/{font_id}", response_class=HTMLResponse)
def design_page(font_id: int, db: Session = Depends(get_db)):
    font = db.query(Font).filter(Font.id == font_id).first()
    if font is None:
        # 폰트 없으면 홈으로 리다이렉트 (soft 404 방지: index를 그냥 주면
        # 검색엔진이 실제 없는 폰트 URL을 계속 재방문할 수 있어 302로 홈 유도)
        return RedirectResponse(url="/", status_code=302)
    html = _load_index()
    html = inject_header(html, "home")
    return HTMLResponse(_replace_meta_for_font(html, font))


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
def home_page():
    """홈 — 서버가 공유 헤더를 주입해서 응답 (헤더 단일 소스화)"""
    html = _load_index()
    return HTMLResponse(inject_header(html, "home"))


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
