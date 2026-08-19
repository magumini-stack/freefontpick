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

from .models import FontView

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


def _too_soon(ip: str, font_id: int) -> bool:
    now = time.time()
    key = (ip, font_id)
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


def prune(db, keep_days: int = 60) -> int:
    """오래된 칸을 지운다. 222종 × 60일이면 최대 1만 3천 행이라 그냥 둬도
    문제는 없지만, 안 지우면 해가 갈수록 는다."""
    try:
        cutoff = date.today() - timedelta(days=keep_days)
        n = db.query(FontView).filter(FontView.day < cutoff).delete()
        db.commit()
        return n or 0
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return 0
