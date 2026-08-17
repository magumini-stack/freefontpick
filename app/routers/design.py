"""디자인 페이지 라우터 — SEO/애드센스용 폰트별 고유 URL

- /font/{font_id}/design → 폰트별 title/description/canonical/OG/JSON-LD가 주입된 font.html
                        (2026-07 URL 구조 변경: 평면 구조였던 /design/{id}를 상세페이지의
                         하위 경로로 이동. 클라이언트에서 경로가 /design으로 끝나는 것을
                         감지해 상세페이지 위에 텍스트 디자인 모달을 자동으로 연다.)
- /design/{font_id}  → 구 URL. /font/{font_id}/design 으로 301 리다이렉트만 수행해
                        기존 검색엔진 색인·외부 백링크 자산을 보존한다.
- /font/{font_id}    → 폰트별 title/description/canonical/OG(폰트별 og-image)/JSON-LD가
                        주입된 font.html (2026-07 추가: 상세페이지 SEO 강화)
- /find-font        → 폰트 찾기 게시판 (SEO용 title/description 변경)

실제 콘텐츠는 SPA(index.html/font.html)가 클라이언트에서 렌더한다.
서버는 <head> 메타데이터만 폰트별로 치환해서, 검색엔진이 개별 페이지로 색인하게 한다.
"""
import html as _html
import json as _json
import re
from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Font, FontPairing, UseCase, UseCaseFont
from ..header import inject_header


def _esc(s) -> str:
    """use_case_route.py와 같은 이스케이프. 어드민이 쓴 자유 문자열이
    본문 HTML로 들어가므로 반드시 거친다."""
    return _html.escape(str(s or ""))

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
    """디자인하기 페이지(/font/{id}/design)용 title/description/keywords/url/og_image 생성

    (2026-07 이관: 텍스트 디자인 모달이 font.html로 옮겨가면서, 이 페이지도
     index.html이 아닌 font.html을 서빙한다. font.html은 상세페이지 콘텐츠를
     보여주면서 모달을 자동으로 연다. 그래서 og_image는 상세페이지와 동일한
     og-image.png를 재사용하되, title/description은 '텍스트 디자인' 의도에 맞춘다.)

    (2026-07 SEO 수정: 이 페이지는 /font/{id}와 실제로 렌더되는 콘텐츠가
     거의 동일(모달 자동오픈 여부만 다름)해서, 구글이 두 URL을 중복 콘텐츠로
     판단해 한쪽만 색인하고 다른 쪽은 "크롤링됨-색인생성안됨"으로 빠뜨렸다.
     canonical(및 og:url)을 /font/{id}로 통일해서 색인을 상세페이지 하나로
     합친다. /font/{id}/design URL 자체는 그대로 동작하며 접속/공유 가능.)
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
    # canonical/og:url은 상세페이지(/font/{id})로 통일 (중복 색인 방지)
    url = f"{BASE_URL}/font/{font.id}"
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


@router.get("/font/{font_id}/design", response_class=HTMLResponse)
def font_design_page(font_id: int, db: Session = Depends(get_db)):
    """디자인하기 고유 URL — font.html(상세페이지)을 서빙하고, 클라이언트에서
    경로가 /design으로 끝나는 것을 감지해 텍스트 디자인 모달을 자동으로 연다.
    (2026-07 URL 구조 변경: /design/{id} 평면 구조에서 /font/{id}/design 계층
     구조로 이동. 상세페이지의 하위 리소스임이 URL로도 드러나고, 상세↔디자인
     간 내부링크가 같은 폰트 안에서의 이동임을 크롤러도 이해하기 쉬워진다.)"""
    font = db.query(Font).filter(Font.id == font_id).first()
    if font is None:
        # 폰트 없으면 홈으로 리다이렉트 (soft 404 방지: index를 그냥 주면
        # 검색엔진이 실제 없는 폰트 URL을 계속 재방문할 수 있어 302로 홈 유도)
        return RedirectResponse(url="/", status_code=302)
    html = _load_font_page()
    html = inject_header(html, "")
    html = _replace_meta_for_design(html, font)
    # 이 페이지도 font.html을 그대로 쓰므로 마커를 채워야 한다.
    # 안 채우면 "{{FFP_SSR}}" 글자가 화면에 그대로 보인다.
    html = html.replace("{{FFP_SSR}}", _font_ssr_block(font, db), 1)
    html = html.replace("{{FFP_USAGE}}", _usage_examples(font), 1)
    return HTMLResponse(html)


@router.get("/design/{font_id}")
def design_page_legacy_redirect(font_id: int):
    """구 URL(/design/{id}) → 신 URL(/font/{id}/design) 301 리다이렉트.

    2026-07 URL 개편 이전에 구글에 색인되었거나 외부에서 걸린 백링크가
    끊기지 않도록, 이 경로 자체는 남겨두고 영구 리다이렉트만 수행한다."""
    return RedirectResponse(url=f"/font/{font_id}/design", status_code=301)


# ── 상세페이지 본문 서버 렌더링 ──────────────────────────────────────
#
# 왜 필요한가 (2026-08, 애드센스 '가치가 별로 없는 콘텐츠' 리젝 대응)
# ------------------------------------------------------------------
# 이 페이지는 <head>만 폰트별로 치환하고 본문은 JS가 채웠다. 그 결과 서버가
# 내려주는 본문이 216개 폰트 전부 **글자 하나까지 같은 1,191자**였다
# (내용은 헤더·푸터와 "폰트 정보를 불러오는 중…"). 사이트맵 250개 중 216개가
# 이 껍데기였고, 구글 판정 기준인 *"pages have enough unique content"* 에
# 정면으로 걸렸다. 게다가 그 1,191자 안에는 라이선스 섹션의 폴백 문구
# ("아직 확인하지 못한 폰트입니다 … 믿고 쓰시면 안 됩니다")가 들어 있어,
# 실제로는 214/216이 확인 완료인데 크롤러는 전 페이지에서 정반대를 읽었다.
#
# 콘텐츠가 없어서가 아니라 안 보여서 생긴 문제다. 큐레이터 코멘트 94%,
# 라이선스 권한표 99%, 조합 95%가 이미 DB에 있다. 그래서 새 글을 쓰지 않고
# 있는 것을 HTML 본문으로 내보낸다.
#
# 방식은 use_case_route.py의 #picksSsr 과 같다 — 서버가 마커를 채우고,
# JS가 뜨면 그 블록을 display:none 으로 덮는다. 크롤러와 JS 차단 환경에는
# 정적 내용이 그대로 남는다.

# 라이선스 권한 키 → 사람이 읽는 이름. 어드민 입력 폼과 같은 8개 축이다.
_PERM_LABELS = [
    ("print", "인쇄물"), ("web", "웹사이트"), ("package", "포장·패키지"),
    ("video", "영상"), ("embed", "임베딩"), ("bici", "BI/CI·로고"),
    ("modify", "수정·개작"), ("redist", "재배포"),
]
_PERM_TEXT = {"y": "가능", "n": "불가", "c": "조건부"}


def _usage_examples(font: Font) -> str:
    """'실제 사용 예시' 세 칸 — 폰트마다 다른 문구로 채운다.

    예전에는 세 문장이 font.html에 하드코딩돼 216개 페이지에 그대로 복사됐다.
    문구는 조합 카드가 쓰는 것과 같은 우물(app/pairing_phrases.py)에서 뽑아
    사이트 전체의 말투를 하나로 맞춘다.

    고르는 기준은 폰트 id다 — 매번 무작위로 뽑으면 같은 폰트를 다시 방문했을
    때 예시가 바뀌어, 서체가 달라 보이는 건지 문구가 달라진 건지 알 수 없다.
    """
    from ..pairing_phrases import THEME_PHRASE_BANK, ENGLISH_THEMES

    is_en = bool(font.is_english)
    themes = [t for t in THEME_PHRASE_BANK
              if (t in ENGLISH_THEMES) == is_en] or list(THEME_PHRASE_BANK)

    fid = font.id or 0
    theme = themes[fid % len(themes)]
    entries = THEME_PHRASE_BANK[theme]
    head_title, head_body = entries[fid % len(entries)]
    sub_title, _ = entries[(fid + 1) % len(entries)]

    # 한글 폰트에도 영문 대체 문구가 필요하다 — JS가 is_english 폰트에서
    # data-en으로 갈아끼운다. 영문 뱅크에서 같은 방식으로 뽑는다.
    en_theme = ENGLISH_THEMES[fid % len(ENGLISH_THEMES)]
    en_entries = THEME_PHRASE_BANK[en_theme]
    en_head, en_body = en_entries[fid % len(en_entries)]
    en_sub, _ = en_entries[(fid + 1) % len(en_entries)]

    rows = [
        ("Headline", "u-h1", 800, head_title, en_head, ""),
        ("Subhead", "u-h2", 700, sub_title, en_sub, "margin-top:28px"),
        ("Body", "u-body", 400, head_body, en_body, "margin-top:28px"),
    ]
    out = []
    for cap, cls, weight, ko, en, cap_style in rows:
        style_attr = f' style="{cap_style}"' if cap_style else ""
        tag = "p" if cls == "u-body" else "div"
        out.append(f'<div class="u-cap"{style_attr}>{cap}</div>')
        out.append(
            f'<{tag} class="{cls} uses-font" style="font-weight:{weight}"'
            f' data-ko="{_esc(ko)}" data-en="{_esc(en)}">{_esc(ko)}</{tag}>'
        )
    return "".join(out)


def _font_ssr_block(font: Font, db: Session) -> str:
    """폰트 상세페이지 본문 — 크롤러가 읽을 수 있는 정적 HTML.

    여기 들어가는 것은 전부 이미 DB에 있는 값이다. 새로 만들어내지 않는다.
    """
    meta = font.meta if isinstance(font.meta, dict) else {}
    parts = []

    name = _esc(font.name)
    maker = _esc(font.maker or "")

    parts.append(f"<h1>{name} 무료폰트</h1>")

    summary = str(meta.get("summary") or "").strip()
    lead = f"{name}은(는) {maker}에서 배포하는 무료 폰트입니다."
    if summary:
        lead += f" {_esc(summary)}"
    parts.append(f"<p>{lead}</p>")

    # 기본 정보 — 폰트마다 값이 달라 이것만으로도 216개가 서로 구분된다
    facts = [("제작사", maker), ("굵기", _esc(font.weights or ""))]
    tags = [t.name for t in font.tags] if font.tags else []
    if tags:
        facts.append(("분류", _esc(" · ".join(tags))))
    parts.append(
        "<ul>" + "".join(f"<li><b>{k}</b> {v}</li>" for k, v in facts if v) + "</ul>"
    )

    # 큐레이터 코멘트 — 폰트픽이 직접 쓴 글. 구글이 요구하는
    # additional commentary 에 가장 정확히 대응하므로 위쪽에 둔다.
    intro = str(meta.get("intro") or "").strip()
    if intro:
        parts.append(
            "<section><h2>왜 골랐나요</h2>"
            f"<p>{_esc(intro)}</p>"
            "<p>— 폰트픽 큐레이션팀</p></section>"
        )

    # 라이선스 권한표 — 직접 조사한 값. 이 사이트의 가장 강한 고유 정보다.
    lic = meta.get("license") if isinstance(meta.get("license"), dict) else None
    if lic and lic.get("verified"):
        perms = lic.get("perms") if isinstance(lic.get("perms"), dict) else {}
        rows = [
            f"<li>{label} — {_PERM_TEXT.get(str(perms.get(key) or '').lower(), '확인 필요')}</li>"
            for key, label in _PERM_LABELS if perms.get(key)
        ]
        block = [f"<section><h2>{name} 라이선스</h2>"]
        if lic.get("name"):
            block.append(f"<p>{_esc(lic['name'])}</p>")
        if rows:
            block.append("<ul>" + "".join(rows) + "</ul>")
        note = str(lic.get("note") or "").strip()
        if note:
            # 줄바꿈이 들어 있는 원문이라 그대로 넣으면 한 덩어리로 뭉친다
            block.append(
                "".join(f"<p>{_esc(ln)}</p>" for ln in note.splitlines() if ln.strip())
            )
        if lic.get("url"):
            block.append(f'<p><a href="{_esc(lic["url"])}" rel="nofollow">저작권자 원문 확인</a></p>')
        block.append("</section>")
        parts.append("".join(block))

    # 어울리는 조합 — 페이지끼리 내부 링크가 생기는 자리이기도 하다.
    # 지금 크롤러는 폰트 페이지 사이를 오갈 링크를 하나도 못 본다.
    pairs = (
        db.query(FontPairing)
        .filter((FontPairing.title_font_id == font.id) | (FontPairing.body_font_id == font.id))
        .order_by(FontPairing.sort_order, FontPairing.id)
        .limit(8)
        .all()
    )
    if pairs:
        items = []
        for p in pairs:
            other = p.body_font if p.title_font_id == font.id else p.title_font
            if other is None:
                continue
            role = "제목" if p.title_font_id == font.id else "본문"
            items.append(
                f'<li><a href="/font/{other.id}">{_esc(other.name)}</a>'
                f" — {_esc(p.theme)}에서 {name}이(가) {role}을 맡는 조합</li>"
            )
        if items:
            parts.append(
                f"<section><h2>{name}과(와) 어울리는 폰트</h2>"
                "<ul>" + "".join(items) + "</ul></section>"
            )

    # 이 폰트가 속한 용도 허브 — 순위와 추천 이유는 이미 써둔 평가 문장이다
    memberships = (
        db.query(UseCaseFont)
        .join(UseCase, UseCase.id == UseCaseFont.use_case_id)
        .filter(UseCaseFont.font_id == font.id, UseCase.is_active.is_(True))
        .order_by(UseCase.sort_order, UseCaseFont.rank)
        .all()
    )
    if memberships:
        items = []
        for m in memberships:
            uc = m.use_case
            if uc is None:
                continue
            line = f'<a href="/use/{_esc(uc.slug)}">{_esc(uc.title)}</a> {m.rank}위'
            if (m.reason or "").strip():
                line += f" — {_esc(m.reason.strip())}"
            items.append(f"<li>{line}</li>")
        if items:
            parts.append(
                f"<section><h2>{name}을(를) 추천한 용도</h2>"
                "<ul>" + "".join(items) + "</ul></section>"
            )

    return f'<div id="fontSsr">{"".join(parts)}</div>'


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

    return html


@router.get("/font/{font_id}", response_class=HTMLResponse)
def font_detail_page(font_id: int, db: Session = Depends(get_db)):
    font = db.query(Font).filter(Font.id == font_id).first()
    if font is None:
        return RedirectResponse(url="/", status_code=302)
    html = _load_font_page()
    html = inject_header(html, "")  # 상세페이지는 nav 항목 중 활성 표시할 게 없음
    html = _replace_meta_for_font_detail(html, font)
    # 본문 서버 렌더링 — 옛 <noscript> 두 줄을 대신한다. 자세한 이유는
    # _font_ssr_block 주석 참조.
    html = html.replace("{{FFP_SSR}}", _font_ssr_block(font, db), 1)
    html = html.replace("{{FFP_USAGE}}", _usage_examples(font), 1)
    return HTMLResponse(html)


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
