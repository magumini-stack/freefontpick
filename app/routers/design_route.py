"""
폰트별 텍스트 디자인 페이지 라우트 (/design/{font_id})
─────────────────────────────────────────────────────
■ 목적
  - 각 폰트마다 고유 URL을 부여해 구글이 개별 페이지로 색인하게 함 (애드센스/SEO)
  - 사용자는 같은 index.html(SPA)을 받지만, <head>의 title/description/OG/canonical이
    폰트별로 서버에서 치환되어 나감 → 검색엔진에는 고유 페이지로 보임

■ 통합 방법
  1) 이 파일을 백엔드 프로젝트에 추가 (예: routers/design.py)
  2) main.py 에서:  app.include_router(design_router)
     ※ 반드시 정적파일 mount, catch-all 라우트보다 "먼저" include 할 것
  3) 아래 get_font_by_id() 부분을 실제 DB 모델에 맞게 수정 (TODO 표시)
  4) sitemap 생성 부분에 add_design_urls_to_sitemap() 반영
"""

import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

design_router = APIRouter()

# index.html 위치 — 프로젝트 구조에 맞게 조정
INDEX_PATH = Path(__file__).parent.parent / "index.html"   # TODO: 실제 경로 확인

BASE_URL = "https://freefontpick.co.kr"


def get_font_by_id(font_id: int):
    """
    TODO: 실제 프로젝트의 DB 세션/모델로 교체하세요.
    예시 (SQLAlchemy):
        from database import SessionLocal
        from models import Font
        with SessionLocal() as db:
            return db.query(Font).filter(Font.id == font_id).first()
    반환 객체는 .name, .maker, .tags (list 또는 콤마 문자열) 속성을 가진다고 가정.
    """
    raise NotImplementedError("DB 조회 코드로 교체 필요")


def _replace_meta(html: str, font) -> str:
    """index.html의 head 메타태그를 폰트별 고유 값으로 치환"""
    name = font.name
    maker = getattr(font, "maker", "") or ""
    tags = getattr(font, "tags", []) or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    title = f"{name} 텍스트 디자인 만들기 - 무료 PNG 저장 | 폰트픽"
    desc = (
        f"{name}({maker}) 폰트로 예쁜 텍스트 디자인을 만들어보세요. "
        f"외곽선, 그라데이션, 그림자 등 다양한 효과를 적용하고 투명배경 PNG로 무료 저장할 수 있습니다."
    )
    url = f"{BASE_URL}/design/{font.id}"

    # <title>
    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1, flags=re.S)
    # meta description
    html = re.sub(
        r'(<meta name="description" content=")[^"]*(")',
        rf"\g<1>{desc}\g<2>", html, count=1,
    )
    # keywords 에 폰트명/태그 추가
    kw_extra = ", ".join([name, f"{name} 다운로드", "텍스트 디자인", "글자 꾸미기"] + tags[:4])
    html = re.sub(
        r'(<meta name="keywords" content=")([^"]*)(")',
        rf"\g<1>\g<2>, {kw_extra}\g<3>", html, count=1,
    )
    # canonical
    html = re.sub(
        r'(<link rel="canonical" href=")[^"]*(")',
        rf"\g<1>{url}\g<2>", html, count=1,
    )
    # OG
    html = re.sub(r'(<meta property="og:title" content=")[^"]*(")', rf"\g<1>{title}\g<2>", html, count=1)
    html = re.sub(r'(<meta property="og:description" content=")[^"]*(")', rf"\g<1>{desc}\g<2>", html, count=1)
    html = re.sub(r'(<meta property="og:url" content=")[^"]*(")', rf"\g<1>{url}\g<2>", html, count=1)

    # 검색엔진용 고유 텍스트 블록(noscript) + JSON-LD 구조화 데이터 삽입
    import json as _json
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
        f'<script type="application/ld+json">{json_ld}</script>\n</head>', 1,
    )
    seo_block = (
        f'<noscript><section><h1>{name} 텍스트 디자인</h1>'
        f"<p>{name}은(는) {maker}에서 제공하는 무료 폰트입니다. "
        f"폰트픽 텍스트 디자인 도구에서 {name} 폰트에 30여 가지 스타일 효과(외곽선, 그림자, "
        f"네온, 그라데이션 등)를 적용하고, 글자색·자간·줄간격을 조절해 "
        f"투명배경 PNG 이미지로 저장할 수 있습니다. "
        f'관련 태그: {", ".join(tags) if tags else "무료폰트"}</p></section></noscript>'
    )
    html = html.replace("</body>", seo_block + "\n</body>", 1)
    return html


@design_router.get("/find-font", response_class=HTMLResponse)
async def find_font_page():
    """폰트 찾아주세요 게시판 고유 URL — index.html을 서빙하고 SPA가 라우팅"""
    html = INDEX_PATH.read_text(encoding="utf-8")
    title = "폰트 찾아주세요 - 이미지로 폰트 이름 찾기 | 폰트픽"
    desc = "찾고 싶은 폰트 이미지를 올리면 폰트 이름을 찾아드립니다. 로그인 없이 무료로 질문하세요."
    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1, flags=re.S)
    html = re.sub(r'(<meta name="description" content=")[^"]*(")', rf"\g<1>{desc}\g<2>", html, count=1)
    html = re.sub(r'(<link rel="canonical" href=")[^"]*(")', rf"\g<1>{BASE_URL}/find-font\g<2>", html, count=1)
    return HTMLResponse(html)


@design_router.get("/design/{font_id}", response_class=HTMLResponse)
async def design_page(font_id: int):
    try:
        font = get_font_by_id(font_id)
    except NotImplementedError:
        font = None
    if font is None:
        # 폰트가 없으면 홈으로 (soft 404 방지를 위해 실제 404도 고려 가능)
        raise HTTPException(status_code=404, detail="Font not found")
    html = INDEX_PATH.read_text(encoding="utf-8")
    return HTMLResponse(_replace_meta(html, font))


# ─────────────────────────────────────────────
# sitemap.xml 에 디자인 페이지 추가
# 기존 sitemap 생성 코드에서 아래 함수를 호출해 <url> 항목들을 병합하세요.
# ─────────────────────────────────────────────
def design_sitemap_entries(fonts) -> str:
    """fonts: 전체 폰트 리스트(id 속성 필요). sitemap <url> 문자열 반환"""
    entries = []
    for f in fonts:
        entries.append(
            f"<url><loc>{BASE_URL}/design/{f.id}</loc>"
            f"<changefreq>monthly</changefreq><priority>0.7</priority></url>"
        )
    return "\n".join(entries)
