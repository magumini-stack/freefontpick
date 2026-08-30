"""어드민 통계 — 무엇을 얼마나 봤는가.

어디서 오는 숫자인가
------------------
두 표에서만 온다. 둘 다 **날짜별 한 칸**이라 기간을 자유롭게 자를 수 있다.

    font_views (font_id, day, count)   폰트 상세페이지
    page_views (kind, key, day, count) 그 밖 — 'use'(용도 허브) · 'pair'(조합)

세는 규칙은 app/font_views.py 한 곳에 있다. 봇 UA 를 거르고, 같은 IP 가
같은 대상을 30분 안에 다시 봐도 한 번만 센다. 안 거르면 상세페이지가
239장이라 숫자를 크롤러가 만든다.

그래서 이 숫자는 **구글 애널리틱스와 다르다.** GA 는 사람 기준 세션을 세고
이쪽은 '거른 페이지 열람'을 센다. 어느 쪽이 맞다기보다 세는 것이 다르다 —
여기 숫자는 사이트 안에서 무엇이 더 읽히는지 견주는 용도다.

기록이 없던 기간
--------------
용도 허브와 조합 페이지는 2026-08-30 부터 센다. 그 전 날짜는 0 으로 나온다.
폰트 상세는 그보다 앞서 쌓여 있다. 기간을 길게 잡으면 이 차이가 보인다.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_password_changed
from ..database import get_db
from ..models import Font, FontView, PageView, UseCase

router = APIRouter(prefix="/api/admin/stats", tags=["admin-stats"])

# 기간은 하루~2년. 상한을 두는 이유는 실수로 days=99999 를 넣었을 때
# 한 해치를 통째로 긁는 질의가 나가지 않게 하려는 것이다.
_MAX_DAYS = 730


def _span(days: int):
    days = max(1, min(int(days or 30), _MAX_DAYS))
    today = date.today()
    return today - timedelta(days=days - 1), today, days


@router.get("/summary")
def summary(days: int = 30, _admin=Depends(require_password_changed),
            db: Session = Depends(get_db)):
    """기간 전체의 합계 한 줄씩. 화면 맨 위 요약 카드가 쓴다."""
    since, today, days = _span(days)

    font_total = db.execute(
        select(func.coalesce(func.sum(FontView.count), 0))
        .where(FontView.day >= since)
    ).scalar() or 0
    font_kinds = db.execute(
        select(func.count(func.distinct(FontView.font_id)))
        .where(FontView.day >= since)
    ).scalar() or 0

    rows = db.execute(
        select(PageView.kind, func.coalesce(func.sum(PageView.count), 0))
        .where(PageView.day >= since).group_by(PageView.kind)
    ).all()
    by_kind = {str(r[0]): int(r[1] or 0) for r in rows}

    return {
        "days": days,
        "from": since.isoformat(),
        "to": today.isoformat(),
        "font_views": int(font_total),
        "font_count": int(font_kinds),        # 조회가 한 번이라도 있던 폰트 수
        "hub_views": by_kind.get("use", 0),
        "pair_views": by_kind.get("pair", 0),
    }


@router.get("/daily")
def daily(days: int = 30, _admin=Depends(require_password_changed),
          db: Session = Depends(get_db)):
    """날짜별 추이. 기록이 없는 날도 0 으로 채워서 준다 —
    빠진 날이 있으면 화면에서 막대 간격이 어긋난다."""
    since, today, days = _span(days)

    f = dict(db.execute(
        select(FontView.day, func.sum(FontView.count))
        .where(FontView.day >= since).group_by(FontView.day)
    ).all())
    p = {}
    for kind, day, n in db.execute(
        select(PageView.kind, PageView.day, func.sum(PageView.count))
        .where(PageView.day >= since).group_by(PageView.kind, PageView.day)
    ).all():
        p.setdefault(str(kind), {})[day] = int(n or 0)

    out = []
    for i in range(days):
        d = since + timedelta(days=i)
        out.append({
            "day": d.isoformat(),
            "font": int(f.get(d, 0) or 0),
            "hub": int(p.get("use", {}).get(d, 0)),
            "pair": int(p.get("pair", {}).get(d, 0)),
        })
    return out


@router.get("/fonts")
def font_stats(days: int = 30, limit: int = 200,
               _admin=Depends(require_password_changed),
               db: Session = Depends(get_db)):
    """폰트별 조회수, 많은 순. 이름은 여기서 붙여 준다 —
    화면이 폰트 목록을 따로 받아 짝지으면 삭제된 폰트에서 어긋난다."""
    since, _today, days = _span(days)
    limit = max(1, min(int(limit or 200), 1000))

    rows = db.execute(
        select(FontView.font_id, func.sum(FontView.count).label("n"))
        .where(FontView.day >= since)
        .group_by(FontView.font_id)
        .order_by(func.sum(FontView.count).desc(), FontView.font_id)
        .limit(limit)
    ).all()
    ids = [int(r[0]) for r in rows]
    names = {}
    if ids:
        names = {f.id: (f.name, f.maker or "")
                 for f in db.query(Font).filter(Font.id.in_(ids)).all()}
    out = []
    for i, (fid, n) in enumerate(rows):
        fid = int(fid)
        nm, maker = names.get(fid, ("(삭제된 폰트)", ""))
        out.append({"rank": i + 1, "id": fid, "name": nm,
                    "maker": maker, "views": int(n or 0)})
    return out


@router.get("/hubs")
def hub_stats(days: int = 30, _admin=Depends(require_password_changed),
              db: Session = Depends(get_db)):
    """용도 허브별 조회수. 한 번도 안 열린 허브도 0 으로 넣는다 —
    목록에서 빠지면 '그런 허브가 없나' 싶어진다."""
    since, _today, days = _span(days)

    rows = db.execute(
        select(PageView.key, func.sum(PageView.count))
        .where(PageView.kind == "use", PageView.day >= since)
        .group_by(PageView.key)
    ).all()
    got = {str(r[0]): int(r[1] or 0) for r in rows}

    hubs = db.query(UseCase).all()
    out = [{"slug": h.slug, "title": h.title,
            "active": bool(h.is_active), "views": got.pop(h.slug, 0)}
           for h in hubs]
    # 표에는 있는데 지금 허브 목록에 없는 slug (지워진 허브)
    for slug, n in got.items():
        out.append({"slug": slug, "title": "(삭제된 허브)",
                    "active": False, "views": n})
    out.sort(key=lambda x: (-x["views"], x["slug"]))
    for i, r in enumerate(out):
        r["rank"] = i + 1
    return out
