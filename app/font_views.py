"""상세페이지 조회수 — 세는 규칙과 최근 순위.

가장 중요한 건 **누구를 세지 않을지**다.

폰트 상세페이지가 222장이라 구글·네이버·애드센스 봇이 통째로 훑는다. 날것으로
세면 순위를 사람이 아니라 크롤러가 정한다. 그래서 두 가지를 거른다.

1. User-Agent 가 봇으로 읽히면 안 센다
2. 같은 사람이 새로고침해도 한 번만 센다 ((IP, font_id) 를 잠깐 기억)

IP 추출과 메모리 캐시는 app/routers/likes.py 가 쓰는 방식을 그대로 따른다 —
카페24가 프록시라 X-Forwarded-For 를 먼저 봐야 하고, 단일 인스턴스라
프로세스 메모리로 충분하다.

숫자는 화면에 드러내지 않는다. 순위만 쓴다 — 방문이 적을 때 '조회 3' 같은
숫자가 보이면 오히려 허술해 보인다.
"""
import time
from datetime import date, timedelta

from sqlalchemy import func, select, update

from .models import FontView, PageView

# ── 봇 거르기 ────────────────────────────────────────────────────
# 이름에 이게 들어가면 세지 않는다. 완벽할 수 없지만, 실제로 사이트를 훑는
# 것들은 대부분 자기를 이렇게 밝힌다.
_BOT_MARKS = (
    "bot", "crawler", "spider", "slurp", "crawling", "bingpreview",
    "facebookexternalhit", "embedly", "quora link preview", "outbrain",
    "pinterest", "vkshare", "w3c_validator", "whatsapp", "flipboard",
    "tumblr", "telegrambot", "applebot", "petalbot", "yeti", "daum",
    "headlesschrome", "python-requests", "curl/", "wget", "go-http-client",
    "okhttp", "java/", "libwww", "httpclient", "lighthouse", "pagespeed",
    "gtmetrix", "chrome-lighthouse", "adsbot", "mediapartners",
)


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    if not ua:
        return True          # UA 를 안 보내는 쪽은 사람이 아니라고 본다
    return any(m in ua for m in _BOT_MARKS)


# ── 같은 사람의 새로고침 거르기 ──────────────────────────────────
# {(ip, font_id): 마지막으로 센 시각}
_DEDUP_WINDOW_SECONDS = 30 * 60      # 30분 안에 같은 폰트를 다시 봐도 한 번
_seen: dict = {}
_MAX_ENTRIES = 50000


def _too_soon(ip: str, what) -> bool:
    """what 은 폰트면 id(int), 다른 페이지면 "kind:key" 문자열이다.
    한 표를 같이 쓰되 타입이 달라 서로 열쇠가 겹치지 않는다."""
    now = time.time()
    key = (ip, what)
    last = _seen.get(key)
    if last is not None and now - last < _DEDUP_WINDOW_SECONDS:
        return True
    if len(_seen) > _MAX_ENTRIES:
        cutoff = now - _DEDUP_WINDOW_SECONDS
        for k, t in list(_seen.items()):
            if t < cutoff:
                _seen.pop(k, None)
    _seen[key] = now
    return False


def record_view(request, font_id: int, db) -> bool:
    """이 조회를 한 번 센다. 세지 않았으면 False.

    실패해도 예외를 밖으로 내보내지 않는다 — 지표 때문에 상세페이지가
    안 뜨면 본말이 뒤집힌다. 부르는 쪽도 try/except 로 감싼다.
    """
    from .routers.likes import _client_ip

    try:
        if is_bot(request.headers.get("user-agent")):
            return False
        if _too_soon(_client_ip(request), font_id):
            return False

        today = date.today()
        # 있으면 +1, 없으면 새로 만든다. MySQL·SQLite 양쪽에서 도는 방식으로
        # 갱신 건수를 보고 갈라 쓴다 (DB별 upsert 문법을 안 쓴다).
        changed = db.execute(
            update(FontView)
            .where(FontView.font_id == font_id, FontView.day == today)
            .values(count=FontView.count + 1)
        ).rowcount
        if not changed:
            db.add(FontView(font_id=font_id, day=today, count=1))
        db.commit()
        return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return False


def top_fonts(db, days: int = 7, limit: int = 10) -> list:
    """최근 N일 조회 합계 상위 font_id 목록 (많은 순).

    조회가 한 번도 없는 폰트는 들어가지 않는다. 배포 직후처럼 자료가 없으면
    빈 목록이 나오고, 화면은 예전과 똑같이 보인다.
    """
    since = date.today() - timedelta(days=days - 1)
    rows = db.execute(
        select(FontView.font_id, func.sum(FontView.count).label("n"))
        .where(FontView.day >= since)
        .group_by(FontView.font_id)
        .order_by(func.sum(FontView.count).desc(), FontView.font_id)
        .limit(limit)
    ).all()
    return [int(r[0]) for r in rows]


# ── 폰트가 아닌 페이지 ──────────────────────────────────────────
#
# 용도 허브와 조합 페이지도 세고 싶은데, FontView 는 font_id 가 fonts 를
# 참조하는 외래키라 담을 수 없다. PageView(kind, key, day) 에 따로 쌓는다.
# 거르는 규칙은 위와 똑같이 쓴다 — 봇, 그리고 30분 내 같은 페이지 새로고침.

def record_page(request, kind: str, key: str, db) -> bool:
    """이 페이지 조회를 한 번 센다. 세지 않았으면 False.

    실패해도 예외를 밖으로 내보내지 않는다 — 지표 때문에 페이지가 안 뜨면
    본말이 뒤집힌다. 부르는 쪽도 try/except 로 감싼다.
    """
    from .routers.likes import _client_ip

    try:
        if is_bot(request.headers.get("user-agent")):
            return False
        kind = (kind or "")[:20]
        key = (key or "")[:120]
        # 폰트 id 자리에 문자열을 넣어 같은 잠깐-기억 표를 함께 쓴다.
        # 폰트 쪽은 int 라 열쇠가 겹치지 않는다.
        if _too_soon(_client_ip(request), "%s:%s" % (kind, key)):
            return False

        today = date.today()
        changed = db.execute(
            update(PageView)
            .where(PageView.kind == kind, PageView.key == key,
                   PageView.day == today)
            .values(count=PageView.count + 1)
        ).rowcount
        if not changed:
            db.add(PageView(kind=kind, key=key, day=today, count=1))
        db.commit()
        return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return False


# ── 급상승 ──────────────────────────────────────────────────────
#
# 왜 필요한가
# ----------
# 누적 상위만 쓰면 순위가 굳는다. 실측(2026-08-30): 7일 상위 10종과 30일 상위
# 10종이 **9종 겹쳤다**. 기간을 늘리든 줄이든 같은 얼굴이었다. 이유가 둘이다.
#
#   1. 누적 총량이라 오래 쌓인 폰트가 이긴다
#   2. 순위에 들면 갤러리 앞으로 당겨지고, 앞에 있으니 더 눌린다(자기강화)
#
# 그래서 '많이 본 폰트'가 아니라 **'갑자기 늘어난 폰트'**를 따로 뽑는다.
# 늘 많이 보는 폰트는 기대치도 높아서 여기서는 저절로 빠진다.
#
#     점수 = 최근 2일 합 − (직전 5일 합 ÷ 5 × 2)
#
# 비율(몇 배 늘었나)이 아니라 차이를 쓰는 이유는, 비율이면 1회가 3회가 된
# 폰트가 300% 급상승으로 1위가 되기 때문이다. 그래도 바닥은 필요해서 최근
# 조회가 _TREND_FLOOR 회 미만이면 후보에서 뺀다.
_TREND_RECENT_DAYS = 2      # '최근'으로 보는 기간
_TREND_BASE_DAYS = 5        # 기대치를 만드는 직전 기간
_TREND_FLOOR = 3            # 최근 조회가 이보다 적으면 후보 아님


def _sum_by_font(db, day_from, day_to=None) -> dict:
    q = select(FontView.font_id, func.sum(FontView.count)).where(FontView.day >= day_from)
    if day_to is not None:
        q = q.where(FontView.day <= day_to)
    rows = db.execute(q.group_by(FontView.font_id)).all()
    return {int(r[0]): int(r[1] or 0) for r in rows}


def trending_fonts(db, limit: int = 10) -> list:
    """기대치보다 얼마나 더 봤는가 — 큰 순서대로 font_id."""
    today = date.today()
    recent_from = today - timedelta(days=_TREND_RECENT_DAYS - 1)
    base_to = recent_from - timedelta(days=1)
    base_from = base_to - timedelta(days=_TREND_BASE_DAYS - 1)

    recent = _sum_by_font(db, recent_from)
    base = _sum_by_font(db, base_from, base_to)

    scored = []
    for fid, n in recent.items():
        if n < _TREND_FLOOR:
            continue
        expect = base.get(fid, 0) / _TREND_BASE_DAYS * _TREND_RECENT_DAYS
        scored.append((n - expect, n, fid))
    # 점수 → 조회수 → id 순. 마지막 id 는 동점일 때 순서를 고정하려는 것이다.
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [int(x[2]) for x in scored[:limit]]


def mixed_top(db, days: int = 7, limit: int = 10) -> list:
    """화면에 나가는 최종 순위 — 인기와 급상승을 한 자리씩 번갈아 놓는다.

        1·3·5·7·9 위   최근 days 일 누적 상위
        2·4·6·8·10 위  급상승 상위

    배지는 둘 다 '인기 N' 으로 나간다. 이용자에게 두 종류의 칩을 보여 주면
    갤러리가 산만해지는데, 어느 쪽이든 '요즘 많이 보는 폰트'인 것은 맞다.

    같은 폰트가 양쪽에 들면 앞자리 한 번만 쓰고 뒤쪽은 다음 후보로 채운다.
    한쪽이 바닥나면(자료가 적은 초기) 다른 쪽에서 마저 채워 열 자리를 지킨다.
    """
    # 겹침으로 빠지는 몫이 있으므로 넉넉히 받아 둔다
    pop = top_fonts(db, days=days, limit=limit * 2)
    tre = trending_fonts(db, limit=limit * 2)

    out, used = [], set()
    cur = {"pop": 0, "tre": 0}

    def take(which):
        src = pop if which == "pop" else tre
        i = cur[which]
        while i < len(src):
            fid = src[i]
            i += 1
            if fid not in used:
                cur[which] = i
                return fid
        cur[which] = i
        return None

    while len(out) < limit:
        want = "pop" if len(out) % 2 == 0 else "tre"
        fid = take(want) or take("tre" if want == "pop" else "pop")
        if fid is None:
            break
        out.append(fid)
        used.add(fid)
    return out


def prune(db, keep_days: int = 400) -> int:
    """오래된 칸을 지운다. 폰트 조회와 페이지 조회 둘 다.

    예전에는 60일만 남겼다. 순위 계산에는 7일이면 충분해서였는데, 어드민
    통계가 붙으면서 '작년 이맘때'를 볼 수 있어야 뜻이 생겼다. 239종 ×
    400일이라도 10만 행 남짓이라 부담이 되지 않는다.
    """
    try:
        cutoff = date.today() - timedelta(days=keep_days)
        n = db.query(FontView).filter(FontView.day < cutoff).delete()
        n += db.query(PageView).filter(PageView.day < cutoff).delete()
        db.commit()
        return n or 0
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return 0
