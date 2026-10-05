"""인기 무료폰트 TOP 100 — /popular (2026-10-05).

사용자님 제안: "메인페이지 용도별 허브 맨 위에 인기 TOP 100 을 만들고, 인기순위별로 100종을 보여주자.
구조는 용도 허브랑 비슷하게, 리스트는 전체 보기의 한 줄 보기처럼." 정하신 것: 최근 7일 기준,
메인에는 1~4위, 순위 변동(▲▼ NEW) 표시, 갈래 필터는 나중에.

순위는 app/font_views.py top100 — 어제까지 7일 상세페이지 조회수(봇·30분 새로고침 제외).
하루에 한 번 바뀌므로 판을 날짜로 갈라 캐시한다. 조회수 숫자는 화면에 내지 않는다(순위만).

화면은 서버가 100줄을 다 그린다(검색엔진이 순위·이름·링크를 그대로 읽는다). 글꼴은 줄이 화면에
들어올 때만 가벼운 미리보기 판(.p)으로 받는다(static/popular.html).
"""
import html as _html
import json as _json
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .. import content_cache
from ..database import get_db
from ..header import inject_header
from ..home_phrases import POPULAR_SAMPLE
from ..models import Font, UseCase
from ..site import SITE_URL, breadcrumb_jsonld

router = APIRouter(tags=["popular"])

TEMPLATE = Path(__file__).resolve().parent.parent.parent / "static" / "popular.html"

_ARROW = ('<span class="go" aria-hidden="true"><svg viewBox="0 0 24 24"><line x1="7" y1="17" x2="17" y2="7"/>'
          '<polyline points="8 7 17 7 17 16"/></svg></span>')


def _esc(s) -> str:
    return _html.escape(str(s or ""), quote=True)


def _js_str(s: str) -> str:
    """<script> 안에 넣을 JS 문자열. '<' 는 유니코드 이스케이프로 바꿔 </script> 로 끊기지 않게."""
    return _json.dumps(s, ensure_ascii=False).replace("<", chr(92) + "u003c")


def _md(d: date) -> str:
    return f"{d.month}월 {d.day}일"


def popular_data(db: Session) -> dict:
    """화면에 그릴 순수 dict (캐시해도 세션과 무관)."""
    from ..font_views import top100
    from .design import _home_font_slim

    t = top100(db)
    ids = [r["font_id"] for r in t["rows"]]
    fonts = {f.id: f for f in db.query(Font).filter(Font.id.in_(ids)).all()} if ids else {}
    rows = []
    for r in t["rows"]:
        f = fonts.get(r["font_id"])
        if f is None:
            continue
        rows.append({"rank": r["rank"], "change": r["change"], "font": _home_font_slim(f),
                     "maker": f.maker or "", "weights": f.weights or "1종"})
    hubs = [(u.slug, u.title) for u in db.query(UseCase).filter(UseCase.is_active.is_(True))
            .order_by(UseCase.sort_order, UseCase.id).all()]
    return {"start": t["start"].isoformat(), "end": t["end"].isoformat(), "rows": rows, "hubs": hubs}


def _change(c) -> str:
    if c is None:
        return '<span class="chg new" title="새로 100위 안에 들어왔어요">NEW</span>'
    if c > 0:
        return f'<span class="chg up" title="하루 전보다 {c}계단 올랐어요">▲{c}</span>'
    if c < 0:
        return f'<span class="chg down" title="하루 전보다 {-c}계단 내려갔어요">▼{-c}</span>'
    return '<span class="chg same" title="하루 전과 같아요">–</span>'


def _row(r: dict) -> str:
    f = r["font"]
    en = bool(f.get("is_english"))
    sample = POPULAR_SAMPLE[1] if en else POPULAR_SAMPLE[0]
    top = " top" if r["rank"] <= 3 else ""
    return (
        f'<a class="row{top}" href="/font/{f["id"]}" data-font-id="{f["id"]}">'
        f'<div class="rk"><b>{r["rank"]}</b>{_change(r["change"])}</div>'
        '<div class="bd">'
        f'<div class="meta"><span class="nm">{_esc(f["name"])}</span>'
        f'<span class="mk">{_esc(r["maker"])}</span><span class="wt">{_esc(r["weights"])}</span></div>'
        f'<div class="pv" data-english="{1 if en else 0}">{_esc(sample)}</div>'
        f'</div>{_ARROW}</a>'
    )


@router.get("/popular", response_class=HTMLResponse)
def popular_page(request: Request, db: Session = Depends(get_db)):
    try:
        from ..font_views import record_page
        record_page(request, "popular", "", db)
    except Exception:
        pass

    data = content_cache.get(f"popular:{date.today().isoformat()}", ttl=1800,
                             build=lambda: popular_data(db))
    rows = data["rows"]
    start, end = date.fromisoformat(data["start"]), date.fromisoformat(data["end"])
    url = f"{SITE_URL}/popular"
    title = "인기 무료폰트 TOP 100 - 이번 주 순위 | 폰트픽"
    names = [r["font"]["name"] for r in rows[:3]]
    lead = ", ".join(f"{i}위 {n}" for i, n in enumerate(names, 1))
    desc = ("최근 7일 폰트픽에서 가장 많이 본 무료폰트 순위입니다. "
            + (f"{lead}. " if lead else "") + "매일 새로 집계해요.")

    item_list = _json.dumps({
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "인기 무료폰트 TOP 100",
        "itemListOrder": "https://schema.org/ItemListOrderDescending",
        "numberOfItems": len(rows),
        "itemListElement": [
            {"@type": "ListItem", "position": r["rank"], "name": r["font"]["name"],
             "url": f"{SITE_URL}/font/{r['font']['id']}"}
            for r in rows
        ],
    }, ensure_ascii=False).replace("</", "<\\/")
    jsonld = (f'<script type="application/ld+json">{item_list}</script>'
              + breadcrumb_jsonld([("폰트픽", "/"), ("인기 TOP 100", "/popular")]))

    body = "".join(_row(r) for r in rows) or (
        '<p class="empty">아직 순위를 낼 만큼 기록이 쌓이지 않았어요. 내일 다시 와 주세요.</p>')
    fonts_json = _json.dumps([r["font"] for r in rows], ensure_ascii=False).replace("<", "\\u003c")
    others = "".join(f'<a href="/use/{_esc(s)}">{_esc(t)}</a>' for s, t in data["hubs"])

    html = TEMPLATE.read_text(encoding="utf-8")
    html = inject_header(html, "")
    for k, v in {
        "{{P_TITLE}}": _esc(title),
        "{{P_DESC}}": _esc(desc),
        "{{P_CANONICAL}}": url,
        "{{P_OG_IMAGE}}": f"{SITE_URL}/og-image-v3.png",
        "{{P_JSONLD}}": jsonld,
        "{{P_DATE}}": _md(end),
        "{{P_PERIOD}}": f"{_md(start)} ~ {_md(end)}",
        "{{P_ROWS}}": body,
        "{{P_FONTS}}": fonts_json,
        # 스크립트 안 문자열이라 HTML 이스케이프가 아니라 JSON 으로 (영문 견본에 ' 가 있다)
        "{{P_SAMPLE_KO}}": _js_str(POPULAR_SAMPLE[0]),
        "{{P_SAMPLE_EN}}": _js_str(POPULAR_SAMPLE[1]),
        "{{P_OTHERS}}": others,
    }.items():
        html = html.replace(k, v)
    return HTMLResponse(html)
