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


def _home_ssr_block(db: Session) -> str:
    """홈 본문 — 크롤러가 읽을 수 있는 정적 HTML.

    왜 바꿨나 (2026-08, 애드센스 리젝 대응)
    ---------------------------------------
    홈도 폰트 상세페이지와 같은 문제였다. 용도 허브(#useSection)는
    display:none으로 시작하고 폰트 갤러리(#fontGrid)는 빈 채로 시작해서,
    서버가 내려주는 본문 1,155자가 **전부 헤더·푸터·안내문**이었다.
    폰트 카드 0개, noscript 밖으로 나가는 /font/ 링크 0개.

    예전에는 <noscript>에 폰트 이름만 나열한 링크 목록을 넣어 뒀는데,
    링크 역할은 해도 콘텐츠는 아니었다(이름만 8,602자). 이제 제작사와
    한줄요약을 함께 넣어 실제 내용이 되게 하고, noscript가 아니라 보이는
    HTML로 내린다 — use.html의 #picksSsr, font.html의 #fontSsr과 같은 방식이다.
    JS가 뜨면 진짜 갤러리가 그려지므로 이 블록은 감춘다.
    """
    parts = []

    # ① 용도 허브 — /use/{slug} 로 가는 진짜 링크. 홈에서 크롤러가 따라갈
    #    내부 링크가 지금은 하나도 없다.
    try:
        hubs = (
            db.query(UseCase)
            .filter(UseCase.is_active.is_(True))
            .order_by(UseCase.sort_order, UseCase.id)
            .all()
        )
    except Exception:
        hubs = []
    if hubs:
        # 부제(subtitle)는 넣지 않는다 — 홈 그리드(#useGrid)가 제목만 보여주므로
        # 부제를 여기 넣으면 화면 어디에도 없는 '크롤러 전용 텍스트'가 된다.
        # 구글이 CSS로 숨긴 텍스트를 금지하므로, 이 블록에는 사용자도 보는 것만 담는다.
        items = "".join(
            f'<li><a href="/use/{_esc(u.slug)}">{_esc(u.title)}</a></li>'
            for u in hubs
        )
        parts.append(
            "<section><h2>어디에 쓰실 건가요</h2>"
            "<ul>" + items + "</ul></section>"
        )

    # ② 폰트 목록 — 갤러리 카드가 보여주는 것과 같은 항목(이름·제작사)만 담는다.
    #    한줄요약(meta.summary)은 카드에 없어서 넣으면 크롤러 전용 텍스트가 된다.
    #    그 요약은 각 폰트 상세페이지에서 이미 본문으로 나가고 있다.
    try:
        fonts = db.query(Font).order_by(Font.sort_order, Font.id).all()
    except Exception:
        fonts = []
    if fonts:
        rows = []
        for f in fonts:
            line = f'<li><a href="/font/{f.id}">{_esc(f.name)}</a>'
            if f.maker:
                line += f" · {_esc(f.maker)}"
            rows.append(line + "</li>")
        parts.append(
            f"<section><h2>무료 폰트 {len(fonts)}종</h2>"
            "<ul>" + "".join(rows) + "</ul></section>"
        )

    if not parts:
        return ""
    return f'<div id="homeSsr">{"".join(parts)}</div>'




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
    return HTMLResponse(_fill_font_markers(html, font, db))


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


_LIC_PENDING_HTML = (
    '<div class="lic-pending" id="licPending" hidden>'
    '<i class="ti ti-alert-triangle"></i>'
    '<div><b>아직 확인하지 못한 폰트입니다.</b> '
    '아래 표는 <u>확인된 내용이 아니라 일반적인 무료폰트 기준</u>이므로 그대로 '
    '믿고 쓰시면 안 됩니다. 사용 전에 반드시 저작권자 페이지에서 직접 확인해 주세요.'
    '</div></div>'
)


def _lic_pending_block(font: Font) -> str:
    """라이선스 미확인 경고 — 정말 미확인인 폰트에만 내려보낸다.

    216종 중 214종이 확인 완료인데, 예전에는 이 경고 마크업이 모든 페이지에
    실려 나갔다(hidden이라 화면에는 안 보였다). 실제 라이선스와 "확인하지
    못했다"는 문장이 한 HTML 안에 같이 있으면 읽는 쪽이 헷갈린다.
    """
    meta = font.meta if isinstance(font.meta, dict) else {}
    lic = meta.get("license") if isinstance(meta.get("license"), dict) else None
    return "" if (lic and lic.get("verified")) else _LIC_PENDING_HTML


# '실제 사용 예시' 문구 10벌.
#
# 조합 문구 뱅크(pairing_phrases.py)에서 뽑아 쓴 적이 있는데, 거기 문장은
# 한 문장이 20자 안팎이라(456개 중 40자 넘는 것이 5개뿐) 본문이 예전의
# 5분의 1로 짧아졌다. 이 자리는 '이 폰트로 제목과 문단을 짜면 어떻게 보이나'를
# 보여주는 곳이라 문단다운 길이가 있어야 한다. 그래서 직접 쓴다.
#
# 결은 원래 있던 문구를 따른다 — 헤드라인은 서정적인 한 줄, 서브헤드는
# 타이포그래피에 대한 짧은 문장, 본문은 이 서체에서 무엇을 살펴봐야 하는지.
# 길이는 대략 헤드라인 16~20자 / 서브헤드 14~18자 / 본문 100~120자.
_USAGE_SETS = [
    ("봄이 오면, 오래된 것들이 새로워진다",
     "좋은 폰트는 문장의 온도를 바꾼다",
     "글꼴은 단순한 장식이 아니라 목소리입니다. 같은 문장도 어떤 폰트로 담느냐에 따라 "
     "다정하게, 단단하게, 혹은 우아하게 들립니다. 화면과 인쇄물 모두에서 안정적으로 "
     "읽히는지 직접 확인해 보세요.",
     "Every great story starts with a single line",
     "Typography sets the tone before words are read",
     "A typeface is not mere decoration but a voice. The same sentence can sound warm, "
     "bold, or elegant depending on the font that carries it. Check how it reads on both "
     "screen and print."),

    ("오래 머문 자리에는 흔적이 남는다",
     "읽는 속도는 서체가 정한다",
     "좋은 서체는 읽는 사람을 재촉하지 않습니다. 획이 고르면 눈이 문장을 따라가는 데 "
     "힘이 들지 않고, 그만큼 오래 읽어도 지치지 않습니다. 긴 글을 얹어 보고 끝까지 "
     "편안한지 확인해 보세요.",
     "What stays long enough leaves a mark",
     "A typeface decides how fast you read",
     "A good typeface never rushes the reader. When the strokes are even, the eye follows "
     "the line without effort and stays with it longer. Set a long passage and see whether "
     "it holds to the end."),

    ("겨울의 끝에서 우리는 조금 자랐다",
     "여백이 문장의 숨을 만든다",
     "글자 사이와 줄 사이의 빈 곳이 문장의 호흡을 정합니다. 같은 서체라도 자간과 행간을 "
     "달리하면 인상이 완전히 달라집니다. 제목과 본문에 각각 올려 보고 두 크기에서 모두 "
     "살아나는지 살펴보세요.",
     "We grew a little at the end of winter",
     "White space gives a sentence its breath",
     "The gaps between letters and lines set the rhythm of a sentence. The same typeface "
     "changes character entirely with different tracking and leading. Try it as a heading "
     "and as body text, and see if it holds at both sizes."),

    ("낡은 것들이 다시 말을 걸어온다",
     "굵기 하나로 위계가 생긴다",
     "크기를 키우지 않아도 굵기만 바꾸면 무엇을 먼저 읽어야 할지 정해집니다. 굵기가 여럿인 "
     "서체는 색을 쓰지 않고도 정보를 정리할 수 있습니다. 제목과 본문의 굵기를 두 단계 "
     "벌려 보고 차이가 또렷한지 보세요.",
     "Old things begin to speak again",
     "Weight alone can build a hierarchy",
     "You do not need a larger size to say what comes first; weight already does it. A "
     "family with many weights can organise information without relying on colour. Put two "
     "steps between heading and body and see if the difference reads."),

    ("멀리 가는 마음은 천천히 걷는다",
     "작게 줄였을 때 진짜가 보인다",
     "서체의 완성도는 크게 키웠을 때가 아니라 작게 줄였을 때 드러납니다. 획이 뭉치거나 "
     "속공간이 막히면 그 크기에서 문장이 무너집니다. 본문 크기까지 내려 보고 글자가 서로 "
     "붙지 않는지 확인해 보세요.",
     "A heart going far walks slowly",
     "The truth shows up at small sizes",
     "A typeface proves itself when it shrinks, not when it grows. If the strokes clot or "
     "the counters close, the sentence collapses at that size. Bring it down to body size "
     "and check that the letters stay apart."),

    ("문 앞에 두고 온 계절이 있다",
     "한글과 영문은 함께 걸어야 한다",
     "한글 옆에 숫자와 알파벳이 나란히 설 때 비로소 서체의 균형이 보입니다. 높이와 굵기가 "
     "어긋나면 한 문장 안에서 두 언어가 따로 놉니다. 날짜와 가격을 섞어 넣고 어색한 곳이 "
     "없는지 살펴보세요.",
     "Some seasons wait outside the door",
     "Latin and numerals must walk together",
     "Balance shows itself when numerals and letters stand beside one another. If height or "
     "weight drifts apart, two scripts pull in different directions inside one line. Mix in "
     "dates and prices and look for the seams."),

    ("아무도 없는 길에서 소리를 들었다",
     "인쇄와 화면은 다른 눈을 쓴다",
     "종이에서 단정하던 서체가 화면에서는 흐리게 번지기도 합니다. 가는 획일수록 그 차이가 "
     "크게 벌어집니다. 쓰려는 환경에서 실제 크기로 띄워 보고 획이 사라지지 않는지 "
     "확인하는 것이 가장 빠릅니다.",
     "I heard something on an empty road",
     "Print and screen ask for different eyes",
     "A face that looks crisp on paper can blur on a display, and the thinner the stroke the "
     "wider that gap becomes. Put it on the medium you actually plan to use, at the size you "
     "plan to use, and see whether the strokes survive."),

    ("여름은 언제나 갑자기 끝난다",
     "제목과 본문은 다른 일을 한다",
     "제목은 붙잡는 일을 하고 본문은 데리고 가는 일을 합니다. 한 서체가 두 가지를 다 잘하는 "
     "경우는 흔치 않습니다. 같은 문장을 큰 크기와 작은 크기로 나란히 놓고 어느 쪽에 더 "
     "어울리는지 가늠해 보세요.",
     "Summer always ends without warning",
     "Headings and body text do different work",
     "A heading has to catch you; body text has to carry you. Few faces do both equally well. "
     "Set the same sentence large and small side by side, and judge which job it is better "
     "suited to."),

    ("돌아오는 길이 더 짧게 느껴졌다",
     "오래 쓸 서체는 조용한 쪽이다",
     "처음 볼 때 눈에 띄는 서체가 반년 뒤에도 좋은 경우는 드뭅니다. 개성이 강할수록 문장의 "
     "내용보다 글자가 먼저 보입니다. 브랜드처럼 오래 쓸 자리라면 며칠 두고 다시 보는 편이 "
     "안전합니다.",
     "The way back always felt shorter",
     "What lasts is usually the quieter face",
     "The typeface that stands out at first sight is rarely the one you still like six months "
     "later. The stronger the character, the more the letters arrive before the meaning. For "
     "something you will keep, look again after a few days."),

    ("잊은 줄 알았던 이름이 떠올랐다",
     "읽히지 않으면 아무 소용이 없다",
     "아무리 아름다운 서체도 읽히지 않으면 제 몫을 못 합니다. 멋과 가독성이 부딪힐 때는 "
     "읽는 쪽을 먼저 챙기는 것이 안전합니다. 처음 보는 사람의 눈으로 한 번 읽어 보고 "
     "걸리는 곳이 있는지 보세요.",
     "A name I thought forgotten came back",
     "Beauty means nothing if it is not read",
     "However handsome a typeface is, it fails when the reader stumbles. Where charm and "
     "legibility pull against each other, it is safer to protect the reading. Read it once "
     "with a stranger's eyes and mark where you snag."),
]


def _usage_examples(font: Font) -> str:
    """'실제 사용 예시' 세 칸 — 폰트마다 다른 문구로 채운다.

    예전에는 세 문장이 font.html에 하드코딩돼 216개 페이지에 그대로 복사됐다.
    위 _USAGE_SETS 열 벌을 폰트마다 돌려 쓴다.

    고르는 기준은 폰트 id다 — 매번 무작위로 뽑으면 같은 폰트를 다시 방문했을
    때 예시가 바뀌어, 서체가 달라 보이는 건지 문구가 달라진 건지 알 수 없다.
    id를 쓰면 폰트마다 다르면서 그 폰트에는 늘 같은 예시가 붙는다.
    """
    fid = font.id or 0
    ko_head, ko_sub, ko_body, en_head, en_sub, en_body = \
        _USAGE_SETS[fid % len(_USAGE_SETS)]

    rows = [
        ("Headline", "u-h1", 800, ko_head, en_head, ""),
        ("Subhead", "u-h2", 700, ko_sub, en_sub, "margin-top:28px"),
        ("Body", "u-body", 400, ko_body, en_body, "margin-top:28px"),
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


# ── '미리 써보기' 기본 문구 ─────────────────────────────────────────
#
# 홈에서 카드를 눌러 들어오면 그 카드의 문구가 sessionStorage로 따라온다.
# 그런데 검색(네이버·구글)에서 상세페이지로 바로 들어오면 이어받을 값이 없어
# 판그램 '다람쥐 헌 쳇바퀴에 타고파'가 그대로 나왔다. 판그램은 자모가 다 들어
# 있는지 보는 시험 문장이라, 서체를 구경하러 온 사람에게는 뜬금없다.
#
# 그래서 폰트마다 다른 일반 문구를 서버가 넣어 준다. 고르는 기준은 폰트 id다
# (_USAGE_SETS와 같은 이유 — 같은 폰트를 다시 열었을 때 문구가 바뀌면 서체가
# 달라 보이는 건지 문구가 달라진 건지 알 수 없다).
_PREVIEW_PHRASES = [
    ("오늘 하루도 잘 지나갔습니다", "Every good day starts here"),
    ("천천히 읽어도 괜찮은 문장입니다", "Take your time with this line"),
    ("작은 차이가 오래 남습니다", "Small details, long remembered"),
    ("좋은 글씨는 먼저 읽힙니다", "Good type reads before it speaks"),
    ("내일은 조금 더 나아질 거예요", "Tomorrow arrives a little brighter"),
    ("한 줄로도 충분한 이야기가 있어요", "Some stories fit in one line"),
    ("계절이 바뀌는 냄새가 납니다", "The season turns overnight"),
    ("오래 두고 볼수록 편안합니다", "Easier on the eyes over time"),
    ("문장의 온도는 서체가 정합니다", "Type sets the tone of a sentence"),
    ("가까이서 보면 더 잘 보입니다", "Look closer and it shows"),
    ("오늘 저녁에는 국수를 삶을까 해요", "Warm bowls for a cool evening"),
    ("적당한 여백이 글을 살립니다", "Whitespace does half the work"),
    ("멀리 가려면 천천히 걸어야죠", "Go slow to go far"),
    ("이 문장을 소리 내어 읽어 보세요", "Try reading this one out loud"),
    ("봄볕이 창가에 오래 머뭅니다", "Sunlight lingers by the window"),
    ("필요한 말만 남기고 지웠어요", "Only what needed saying"),
    ("처음 만든 것을 아직 갖고 있어요", "Still keeping the very first one"),
    ("읽는 사람을 재촉하지 않습니다", "It never rushes the reader"),
    ("조용한 아침이 가장 좋습니다", "Quiet mornings suit us best"),
    ("끝까지 읽어 주셔서 고맙습니다", "Thanks for reading to the end"),
]

_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㆎ]")


def _preview_phrase(font: Font) -> tuple:
    """이 폰트의 '미리 써보기' 기본 문구 (한글용, 영문용).

    어드민이 폰트에 문구를 지정해 뒀으면(meta.preview_text) 그게 우선이다.
    다만 영문 전용 폰트에 한글 문구가 들어 있으면 글자가 통째로 깨지므로
    그때는 쓰지 않는다 — 홈(index.html getPreviewTextFor)과 같은 규칙이다.
    """
    ko, en = _PREVIEW_PHRASES[(font.id or 0) % len(_PREVIEW_PHRASES)]
    meta = font.meta or {}
    own = str(meta.get("preview_text") or "").strip()
    if own:
        if font.is_english:
            if not _HANGUL_RE.search(own):
                en = own
        else:
            ko = own
    return ko, en


def _fill_font_markers(html: str, font: Font, db: Session) -> str:
    """font.html의 {{FFP_*}} 마커를 전부 채운다.

    /font/{id} 와 /font/{id}/design 이 같은 파일을 쓴다. 예전에는 두 라우트가
    같은 replace 네 줄을 각각 갖고 있어서, 마커를 하나 추가할 때 한쪽만 고치면
    그 페이지에 "{{FFP_...}}" 글자가 그대로 보였다. 한 곳에 모은다.
    """
    ko, en = _preview_phrase(font)
    return (
        html.replace("{{FFP_SSR}}", _font_ssr_block(font, db), 1)
            .replace("{{FFP_USAGE}}", _usage_examples(font), 1)
            .replace("{{FFP_LIC_PENDING}}", _lic_pending_block(font), 1)
            .replace("{{FFP_HUBS}}", _font_hub_block(font, db), 1)
            .replace("{{FFP_TRY_KO}}", _esc(ko), 1)
            .replace("{{FFP_TRY_EN}}", _esc(en), 1)
    )


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

    # 기본 정보 — 폰트마다 값이 달라 이것만으로도 216개가 서로 구분된다.
    # 태그(분류)는 넣지 않는다: 화면에서 뺀 항목이라(font.html 주석 참고 —
    # "예전에는 이 자리에 카테고리 태그 알약이 깔렸는데") 여기 넣으면 사용자에게는
    # 없고 크롤러에게만 있는 텍스트가 된다.
    facts = [("제작사", maker), ("굵기", _esc(font.weights or ""))]
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

    return f'<div id="fontSsr">{"".join(parts)}</div>'


def _font_hub_block(font: Font, db: Session) -> str:
    """이 폰트를 추천한 용도 허브 — 화면에 계속 보이는 섹션.

    #fontSsr 안에 있던 것을 떼어냈다. 그 블록은 JS가 뜨면 감추는데 화면 어디에도
    같은 내용이 없어서, 크롤러만 읽는 텍스트가 되고 있었다(블록의 27%).
    구글은 CSS로 숨긴 텍스트를 금지하므로 지우거나 보이게 해야 하는데,
    순위와 추천 이유는 사용자에게도 쓸모 있는 정보라 보이는 쪽을 택했다.
    """
    memberships = (
        db.query(UseCaseFont)
        .join(UseCase, UseCase.id == UseCaseFont.use_case_id)
        .filter(UseCaseFont.font_id == font.id, UseCase.is_active.is_(True))
        .order_by(UseCase.sort_order, UseCaseFont.rank)
        .all()
    )
    items = []
    for m in memberships:
        uc = m.use_case
        if uc is None:
            continue
        line = (f'<a href="/use/{_esc(uc.slug)}"><b>{_esc(uc.title)}</b></a>'
                f' <span class="hub-rank">{m.rank}위</span>')
        if (m.reason or "").strip():
            line += f" — {_esc(m.reason.strip())}"
        items.append(f"<li>{line}</li>")
    if not items:
        return ""
    return (
        '<section class="blk" id="hubSec">'
        f'<div class="sec-head"><h2>{_esc(font.name)}을(를) 추천한 용도</h2></div>'
        '<ul class="hub-list">' + "".join(items) + "</ul></section>"
    )


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
    return HTMLResponse(_fill_font_markers(html, font, db))


@router.get("/", response_class=HTMLResponse)
@router.get("/index.html", response_class=HTMLResponse)
def home_page(db: Session = Depends(get_db)):
    """홈 — 서버가 공유 헤더를 주입해서 응답 (헤더 단일 소스화)

    + 용도 허브와 전체 폰트 목록을 본문 HTML로 심는다(_home_ssr_block).
      갤러리와 허브 그리드가 모두 JS로 그려져서, 서버 응답만 보면 헤더·푸터밖에
      없던 것을 메운다.
    """
    html = _load_index()
    html = inject_header(html, "home")
    html = html.replace("{{FFP_HOME_SSR}}", _home_ssr_block(db), 1)
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
    # 이 페이지도 index.html을 그대로 쓴다. 마커를 안 지우면 "{{FFP_HOME_SSR}}"
    # 글자가 화면에 그대로 보인다. 홈의 폰트 목록은 여기 붙일 내용이 아니므로
    # 빈 문자열로 지운다 — 같은 목록이 두 URL에 실리면 중복 콘텐츠가 된다.
    html = html.replace("{{FFP_HOME_SSR}}", "", 1)
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


# ── 폰트 조합 찾기 (/font-pair) ─────────────────────────────────────
#
# 상세페이지의 조합 모달을 대신하는 독립 페이지. 모달은 URL이 없어 공유도
# 색인도 안 됐다.
#
# 헤더 메뉴에는 아직 넣지 않는다 — 화면이 자리를 잡을 때까지 주소로만 들어간다.
# 사이트맵에도 그때 함께 넣는다(미완성 페이지를 검색엔진에 먼저 알릴 이유가 없다).

def _pair_ssr_block(db: Session) -> str:
    """오른쪽 칸 아래 사용팁 — 화면에도 그대로 보이는 자리다.

    통째로 없애지는 않는다. 이 페이지는 JS로 그려져서 이 블록이 빠지면 크롤러가
    읽는 본문이 메뉴·버튼 이름뿐이 된다. 감춰 두고 크롤러에게만 보여주는 것은
    위반이므로, 사람이 읽어도 쓸모 있는 문장으로 둔다.

    화면이 이미 말하고 있는 것("고른 자리의 틀에 세 폰트를 앉힌다")은 적지
    않는다. 보면 아는 것을 글로 다시 설명하면 읽지 않게 된다. 눌러 보기 전에는
    모르는 것만 남긴다.
    """
    return (
        '<section class="fp-about">'
        "<h2>사용팁</h2>"
        "<ul>"
        "<li>마음에 드는 폰트는 <b>자물쇠</b>로 잠그세요. 새로 뽑아도 그대로 있습니다.</li>"
        "<li><b>문구</b>를 눌러 직접 고쳐 쓸 수 있습니다.</li>"
        "<li>아래 <b>막대</b>를 끌면 글자 크기가 바뀝니다.</li>"
        "<li><b>폰트 이름</b>을 누르면 다운로드와 라이선스로 갑니다.</li>"
        "</ul>"
        "</section>"
    )


@router.get("/font-pair", response_class=HTMLResponse)
def font_pair_page(db: Session = Depends(get_db)):
    html = (STATIC_DIR / "font-pair.html").read_text(encoding="utf-8")
    html = inject_header(html, "")
    html = html.replace("{{FFP_PAIR_SSR}}", _pair_ssr_block(db), 1)

    title = "폰트 조합 찾기 - 제목·본문 폰트 짝 맞추기 | 폰트픽"
    desc = ("제목·서브타이틀·본문에 쓸 무료 폰트 세 가지를 한 화면에서 맞춰 보세요. "
            "쓰는 자리별 추천, 슬롯 잠금, 문구 편집, 글자 크기 조절까지 "
            "무료로 씁니다.")
    url = f"{BASE_URL}/font-pair"

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
