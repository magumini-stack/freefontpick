"""읽기 응답 캐시 — 폰트 목록·홈 본문처럼 매번 같은 답을 DB 에서 다시 만드는 것을 막는다.

왜 (2026-09-22 실측)
------------------
/api/fonts 가 0.7~2.2초, 홈 HTML 이 0.4~0.5초였다. 폰트 296종마다 파일 존재를
재고(stat), meta 사본을 만들고, pydantic 으로 검증해 JSON 으로 굽는 일을
방문자마다 되풀이한 탓이다. 답은 어드민이 뭔가를 고치기 전까지 늘 같다.

어떻게
------
값은 프로세스 메모리에 두고 두 가지로 낡음을 판단한다.
  ① 내용 판(version): 폰트·태그·용도·조합처럼 화면 내용이 되는 표에 커밋이
     일어나면 올라간다(아래 SQLAlchemy 훅). 어드민이 고치면 다음 요청부터 새 답.
  ② TTL: 훅이 못 보는 변화(파일 교체, 조회수 기반 인기 순위)를 위한 안전망.
캐시 키에 판이 들어가므로 판이 오르면 옛 항목은 그냥 버려진다.

uvicorn 워커가 하나라 메모리 캐시로 충분하다. 워커를 늘리면 워커마다 따로
캐시를 갖는데, 그래도 틀린 답이 아니라 '조금 늦은 답'일 뿐이다(TTL 안).
"""
import threading
import time

_lock = threading.Lock()
_version = 0
_store: dict = {}

# 이 표가 바뀌면 캐시가 낡는다. 조회수(font_views·page_views)·공지·문의 게시판은
# 여기 없다 — 그것들이 바뀔 때마다 폰트 목록을 다시 굽는 것은 낭비다.
_CONTENT_TABLES = frozenset({
    "fonts", "font_tags", "font_weights", "tags", "font_pairings",
    "use_cases", "use_case_fonts", "use_case_phrases", "preview_phrases",
})


def version() -> int:
    return _version


def bump() -> None:
    """내용이 바뀌었다고 알린다. 다음 요청부터 모든 캐시 항목을 새로 만든다."""
    global _version
    with _lock:
        _version += 1
        _store.clear()


def get(key: str, ttl: float, build):
    """key 의 값을 돌려준다. 없거나 낡았으면 build() 로 만들어 넣는다.

    build 는 DB 세션을 닫힌 뒤에도 쓸 수 있는 순수 값(dict·list·str·bytes)을
    돌려줘야 한다 — ORM 객체를 넣으면 세션이 끝난 뒤 지연 로딩에서 죽는다.
    """
    now = time.monotonic()
    full = (_version, key)
    hit = _store.get(full)
    if hit and hit[0] > now:
        return hit[1]
    value = build()
    with _lock:
        _store[full] = (now + ttl, value)
    return value


def _mark_if_content(session, *_):
    """flush 직전: 이번 트랜잭션이 내용 표를 건드리는지 표시해 둔다."""
    if session.info.get("content_changed"):
        return
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        table = getattr(getattr(obj, "__table__", None), "name", None)
        if table in _CONTENT_TABLES:
            session.info["content_changed"] = True
            return


def _bump_if_marked(session):
    if session.info.pop("content_changed", False):
        bump()


def install(session_factory) -> None:
    """sessionmaker 에 훅을 단다. app/main.py 가 기동 때 한 번 부른다."""
    from sqlalchemy import event
    event.listen(session_factory, "before_flush", _mark_if_content)
    event.listen(session_factory, "after_commit", _bump_if_marked)
