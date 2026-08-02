"""용도 허브 페이지 SSR — GET /use/{slug}

wisefont.py / design.py와 동일한 방식이다: static/use.html의 {{UC_*}} 마커를
서버가 치환해서 내려준다. 페이지마다 고유한 title·description·JSON-LD가
HTML에 박혀 있어야 검색엔진이 허브를 각각 다른 페이지로 색인한다.
JS로 채우면 색인이 안 되거나 전부 같은 페이지로 취급된다 — 이 페이지들을
만드는 목적 자체가 그거라서 SSR이 필수다.

추천 폰트도 서버에서 렌더한다(#picksSsr). JS가 뜨면 미리보기가 들어간
카드로 교체되지만, 크롤러와 JS 차단 환경에서는 정적 목록이 그대로 남는다.
"""
import html as _html
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import UseCase, Font, Tag
from ..header import inject_header

router = APIRouter(tags=["use-case-page"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_PATH = BASE_DIR / "static" / "use.html"
BASE_URL = "https://freefontpick.co.kr"


def _esc(s) -> str:
    return _html.escape(str(s or ""))


@router.get("/use/{slug}", response_class=HTMLResponse)
def use_case_page(slug: str, db: Session = Depends(get_db)):
    uc = db.query(UseCase).filter(UseCase.slug == slug).first()
    if uc is None or not uc.is_active:
        # 없는 허브는 홈으로 — soft 404 방지 (wisefont.py와 동일한 처리)
        return RedirectResponse(url="/", status_code=302)

    # 1~4위만 추천 이유를 단 카드로 노출하고, 5위 이후는 목록으로 내려간다.
    PICK_CARD_LIMIT = 4
    linked = [f for f in uc.fonts if f.font is not None]
    picks = linked[:PICK_CARD_LIMIT]
    rest = linked[PICK_CARD_LIMIT:]
    linked_ids = {f.font_id for f in linked}

    more_count = len(rest)
    if uc.tag_id:
        q = db.query(Font).join(Font.tags).filter(Tag.id == uc.tag_id)
        if linked_ids:
            q = q.filter(~Font.id.in_(linked_ids))
        more_count += q.count()
    total = len(picks) + more_count

    url = f"{BASE_URL}/use/{slug}"
    title = f"{uc.title} 무료폰트 추천 {total}종 - 상업적 이용 가능 | 폰트픽"
    desc = (
        f"{uc.title}에 어울리는 무료 한글 폰트 {total}종을 골랐습니다. "
        f"{uc.subtitle}. 선정 기준과 활용 방법까지 함께 확인하세요."
    )
    # 추천 1순위 폰트의 OG 이미지를 대표로 쓴다 (이미 디스크 캐시된 자산).
    # 없을 경우에만 사이트 기본 이미지로 폴백.
    og_image = f"{BASE_URL}/og-image-v3.png"
    if picks:
        og_image = f"{BASE_URL}/api/fonts/{picks[0].font_id}/og-image.png"

    # ── JSON-LD: 추천 4종을 ItemList로 노출 ──────────────────
    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "description": desc,
        "url": url,
        "inLanguage": "ko",
        "isPartOf": {"@type": "WebSite", "name": "폰트픽", "url": BASE_URL},
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(picks),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": p.rank,
                    "name": p.font.name,
                    "url": f"{BASE_URL}/font/{p.font_id}",
                    "description": p.reason,
                }
                for p in picks
            ],
        },
    }, ensure_ascii=False)

    # ── 서버 렌더 추천 목록 (크롤러 / JS 차단 환경용) ──────────
    picks_ssr = "<ul class=\"ssr-list\">" + "".join(
        f'<li><a href="/font/{p.font_id}"><strong>{_esc(p.font.name)}</strong></a>'
        f' — {_esc(p.reason)}</li>'
        for p in picks
    ) + "</ul>"
    # 5위 이후도 이름만이라도 HTML에 남긴다 — 크롤러가 이 페이지에서
    # 어떤 폰트를 다루는지 알 수 있어야 하고, JS 차단 환경에서도 목록이 보여야 한다.
    if rest:
        picks_ssr += (
            '<p class="ssr-list" style="margin-top:10px">그 밖에 '
            + ", ".join(
                f'<a href="/font/{r.font_id}">{_esc(r.font.name)}</a>' for r in rest
            )
            + " 등이 있습니다.</p>"
        )

    # ── 활용 방법 3단 ──
    # [라벨, 내용]을 좌우로 갈라 렌더한다. 한 문단으로 붙이면 숫자가 문장 속에
    # 묻혀 안 읽힌다 — 규격을 주는 게 이 페이지의 핵심이라 스캔이 되게 해야 한다.
    tips = [t for t in (uc.tips or []) if t and len(t) >= 2 and t[0] and t[1]]
    if tips:
        howto_html = "".join(
            f'<div class="tip-row"><span class="tip-k">{_esc(t[0])}</span>'
            f'<span class="tip-v">{_esc(t[1])}</span></div>'
            for t in tips
        )
    else:
        # 구버전 데이터(한 문단) 폴백
        howto_html = f'<p>{_esc(uc.howto)}</p>'

    phrase_chips = "".join(
        f'<button type="button" class="chip" data-text="{_esc(ph.text)}">{_esc(ph.text)}</button>'
        for ph in uc.phrases
    )

    # ── 다른 허브 내부 링크 (사이트 내 순환 + 색인 도움) ────────
    others = (
        db.query(UseCase)
        .filter(UseCase.is_active.is_(True), UseCase.slug != slug)
        .order_by(UseCase.sort_order, UseCase.id)
        .all()
    )
    other_links = "".join(
        f'<a href="/use/{o.slug}">{_esc(o.title)}</a>' for o in others
    )

    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = inject_header(html, "")

    repl = {
        "{{UC_TITLE}}": _esc(title),
        "{{UC_DESC}}": _esc(desc),
        "{{UC_CANONICAL}}": url,
        "{{UC_OG_IMAGE}}": og_image,
        "{{UC_JSONLD}}": f'<script type="application/ld+json">{json_ld}</script>',
        "{{UC_H1}}": _esc(f"{uc.title} 무료폰트 추천"),
        "{{UC_H1_SHORT}}": _esc(uc.title),
        "{{UC_SUBTITLE}}": _esc(uc.subtitle),
        "{{UC_COUNT}}": str(total),
        "{{UC_CRITERIA}}": _esc(uc.criteria),
        "{{UC_HOWTO}}": howto_html,
        "{{UC_PHRASE_CHIPS}}": phrase_chips,
        "{{UC_PICKS_SSR}}": picks_ssr,
        "{{UC_OTHERS}}": other_links,
        "{{UC_SLUG}}": slug,
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    return HTMLResponse(html)
