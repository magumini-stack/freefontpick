"""조합 페이지(/font-pair) 전용 추천 엔진 — 단독으로 선다.

왜 따로 만들었나
---------------
1차에서는 `pairings.py`의 auto-generate 부품을 빌려 썼다. 그런데 그 쪽 카테고리
필터는 **저장된 FontPairing 1,272건에서 학습한 테마 프로파일**을 쓴다. 그래서
저장 조합에 한 번도 안 쓰인 폰트는 어느 프로파일과도 유사도가 0에 가까워
후보에서 밀려난다. 실측 결과가 그대로 나왔다 — 카테고리마다 40회(120슬롯)를
돌렸을 때:

    브랜딩 · 로고   21종 등장 / 상위 5종이 49% 차지
    본문 · 읽기     20종 등장 / 상위 5종이 47%
    뜻밖의 발견     85종 등장 / 상위 5종이 14%   ← 점수 계산을 건너뛰는 자리

한글 폰트가 180종인데 브랜딩은 12%만 썼다. 마지막 줄이 결정적이다 — 점수를
안 쓰는 '뜻밖의 발견'만 넓게 뽑았으니, 좁히는 주범이 점수 파이프라인이다.
새 폰트를 아무리 추가해도 이 페이지에는 나오지 않는 구조였다.

그래서 이 모듈은 **FontPairing을 읽지 않는다.** 폰트 자체에서 나오는 것만 본다:
`app/font_metrics.py`의 실측값, `Font.meta`, `font.tags`, `Font.is_english`,
`FontWeight`. 저장 조합이 0건이어도 똑같이 동작한다.

무엇을 근거로 고르나
------------------
실측값 세 축이 뼈대다 (font_metrics.py):
    d  채움비율 = 실제 굵기      x  글자 높이      w  글자 폭
메타의 `weight_feel`은 70%가 "보통"이라 사실상 상수라서 쓰지 않는다. 실측 d가
같은 일을 훨씬 정확히 한다 — font_metrics.py가 `usWeightClass`를 버린 것과 같은
이유다.

모양마다 제목이 원하는 **백분위 목표**를 손으로 적어 둔다(아래 TITLE_TARGET).
절대값이 아니라 백분위라, 폰트가 늘거나 측정 기준이 바뀌어도 뜻이 유지된다.
"""
import math
import random
from collections import deque

from .font_metrics import metrics_of
from .pair_specimens import (BODY_EXCLUDE, BODY_SHAPES, SHAPES,
                             SURPRISE_KEY, get_shape, specimen)

# ── 모양별 슬롯 목표 ─────────────────────────────────────────────
#
# d/w/x 는 **백분위 목표**(0=가장 가는 쪽, 1=가장 굵은 쪽)다. 적지 않은 축은
# 점수에 넣지 않는다 — 상관없는 자리까지 묶으면 후보만 좁아진다.
#
# 제목은 고른 모양에서, 본문은 늘 고딕·명조에서 고른다(BODY_SHAPES).
# 그래서 목표도 제목만 모양마다 다르고 본문은 하나로 둔다 — 본문에 요구하는
# 것은 계열이 무엇이든 '오래 읽어도 지치지 않는가' 하나뿐이다.
TITLE_TARGET = {
    "gothic":  {"d": 0.65},
    "serif":   {"d": 0.55},
    "hand":    {"d": 0.45},
    "display": {"d": 0.80, "w": 0.65},
    "cute":    {"d": 0.60},
}
BODY_TARGET = {"d": 0.35, "x": 0.60}

# 모양 → 그 계열로 인정하는 태그. pair_specimens.SHAPES 에서 그대로 가져온다.
SHAPE_TAGS = {c["key"]: set(c["tags"]) for c in SHAPES}

# 본문으로 인정하는 태그(고딕 + 명조)를 미리 합쳐 둔다.
BODY_TAGS = set()
for _k in BODY_SHAPES:
    BODY_TAGS |= SHAPE_TAGS[_k]

# 후보를 이만큼도 못 남기면 거르지 않는다. 걸러서 텅 비는 것보다 낫다.
_MIN_POOL = 8


def _tags(font) -> set:
    return {t.name for t in (font.tags or [])}


def _in_shape(font, shape: str) -> bool:
    """이 폰트가 그 모양 계열인가."""
    return bool(_tags(font) & SHAPE_TAGS.get(shape, set()))


def _body_ok(font) -> bool:
    """본문으로 써도 되는 폰트인가.

    고딕·명조여야 하고, 그중에서도 장식·손글씨 성격을 겸하는 것은 뺀다.
    한 폰트가 두 계열에 걸치는 경우가 실제로 있어서(고딕이면서 디스플레이)
    계열만 보고 넣으면 문단이 읽히지 않는다.
    """
    t = _tags(font)
    return bool(t & BODY_TAGS) and not (t & BODY_EXCLUDE)


# 최근에 내보낸 폰트를 잠시 피한다. 연속으로 누를 때 같은 얼굴이 또 나오면
# "안 바뀐다"로 읽힌다. 프로세스 메모리라 재시작하면 비워진다 — 그래도 된다.
_RECENT = deque(maxlen=90)
_RECENT_PENALTY = 3.0

# 점수를 확률로 바꿀 때의 온도. 낮으면 1등만, 높으면 아무나.
# 실측으로 정했다. 카테고리 7종 × 40회(120슬롯)를 돌려 등장 폰트 수와 상위
# 5종 점유를 재면:
#     0.6  최악 38종 / 33%
#     0.9  최악 62종 / 27%   ← '본문 · 읽기'만 목표(60종·25%)에 못 미쳤다
#     1.2  최악 71종 / 20%   ← 7종 전부 통과
# 더 올리면 다양성은 조금 더 늘지만 추천이 무작위에 가까워진다.
_TEMPERATURE = 1.2


def _percentiles(fonts):
    """실측 세 축의 백분위 표. 절대값을 그대로 비교하지 않는 이유는,
    폰트가 늘거나 측정 기준이 바뀌어도 '굵은 축에 속하는가'라는 뜻이
    유지되어야 하기 때문이다."""
    cols = {"x": [], "w": [], "d": []}
    vals = {}
    for f in fonts:
        m = metrics_of(f.id)
        if not m:
            continue
        vals[f.id] = {"x": m[0], "w": m[1], "d": m[2]}
        cols["x"].append(m[0])
        cols["w"].append(m[1])
        cols["d"].append(m[2])
    for k in cols:
        cols[k].sort()

    def pct(axis, v):
        arr = cols[axis]
        if not arr:
            return 0.5
        lo, hi = 0, len(arr)
        while lo < hi:
            mid = (lo + hi) // 2
            if arr[mid] < v:
                lo = mid + 1
            else:
                hi = mid
        return lo / max(1, len(arr) - 1)

    out = {}
    for fid, v in vals.items():
        out[fid] = {k: pct(k, v[k]) for k in ("x", "w", "d")}
    return out


def _slot_score(font, pcts, prof_slot, cat_prof):
    """이 폰트가 그 슬롯에 얼마나 맞는가. 0을 기준으로 오르내린다."""
    p = pcts.get(font.id)
    s = 0.0
    if p:
        for axis, target in prof_slot.items():
            # 목표 백분위에 가까울수록 +2, 정반대면 −2
            s += (1.0 - abs(p[axis] - target) * 2.0) * 2.0
    else:
        # 실측값이 없는 폰트는 이 항목이 빠질 뿐 감점하지 않는다.
        # (지금은 221종 전부 값이 있지만, 새 폰트가 들어오면 측정 전까지 여기 온다)
        s += 0.0

    names = {t.name for t in (font.tags or [])}
    for t, w in cat_prof.get("tags", {}).items():
        if t in names:
            s += w
    usage = set((font.meta or {}).get("usage") or [])
    for u, w in cat_prof.get("usage", {}).items():
        if u in usage:
            s += w
    return s


def _contrast(t_font, b_font, pcts):
    """제목이 본문보다 충분히 굵은가. 실측 d의 백분위 차이로 본다."""
    a, b = pcts.get(t_font.id), pcts.get(b_font.id)
    if not a or not b:
        return 0.0
    gap = a["d"] - b["d"]
    if gap < 0:
        return max(-6.0, gap * 12.0)      # 역전 — 위계가 무너진다
    if gap < 0.12:
        return gap / 0.12 * 2.0 - 2.0     # 차이가 없어 실수처럼 보인다
    if gap <= 0.55:
        return 3.0
    return max(0.5, 3.0 - (gap - 0.55) * 5.0)


def _harmony(a_font, b_font, pcts):
    """글자 높이·폭이 서로 닮았는가. 너무 다르면 한 화면에서 따로 논다."""
    a, b = pcts.get(a_font.id), pcts.get(b_font.id)
    if not a or not b:
        return 0.0
    dx = abs(a["x"] - b["x"])
    dw = abs(a["w"] - b["w"])
    return max(-2.0, 1.5 - dx * 3.0) + max(-2.0, 1.5 - dw * 3.0)


def _weighted_pick(scored):
    """점수를 확률로 바꿔 뽑는다.

    점수를 그대로 지수에 넣으면 안 된다. 태그 가산점이 몇 점이냐에 따라
    확률 분포가 통째로 달라지기 때문이다 — 실제로 '본문 · 읽기'는 태그가
    잘 맞는 두 폰트(Noto Sans·프리텐다드)가 40회 중 46회 슬롯을 차지했다.
    평균 0 · 표준편차 1로 표준화하고 ±2에서 자른 뒤 온도를 걸면, 표의 값을
    고쳐도 다양성이 흔들리지 않는다.
    """
    if not scored:
        return None
    vals = [s for s, _ in scored]
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    sd = math.sqrt(var) or 1.0

    weights = []
    for v in vals:
        z = max(-2.0, min(2.0, (v - mean) / sd))
        weights.append(math.exp(z / _TEMPERATURE))
    return random.choices([f for _, f in scored], weights=weights, k=1)[0]


def is_english(font) -> bool:
    """이 폰트에 한글을 얹으면 깨지는가.

    태그만 보면 '본문용 영어' 계열 5종(LibreBodoni·Montserrat·OpenSans·
    Playfair Display·Roboto)이 한글 폰트로 분류된다. is_english 컬럼이
    프론트가 쓰는 값이자 더 정확하므로 그것을 우선한다.
    """
    if getattr(font, "is_english", False):
        return True
    return bool({t.name for t in (font.tags or [])} & {"디자인 영어", "본문용 영어",
                                                       "디자이너 필수 영문"})


def script_pools(script: str, fonts: list):
    """(제목 후보, 서브·본문 후보). 나누는 기준은 취향이 아니라
    '그 문구가 그려지는가'다. mix는 제목만 영문 — specimen()의 mix와 같은 배치."""
    eng = [f for f in fonts if is_english(f)]
    kor = [f for f in fonts if not is_english(f)]
    if script == "en":
        return eng, eng
    if script == "mix":
        return eng, kor
    return kor, kor


def font_brief(f) -> dict:
    """프론트가 폰트를 그리는 데 필요한 필드 일습.

    pairings.py에도 같은 함수가 있지만 가져다 쓰지 않는다. 이 모듈이 저장
    조합 쪽 코드에 묶이지 않는 것이 요점이라, 응답 모양까지 여기서 갖는다.
    file_source는 빼면 안 된다 — 프론트가 "어드민이 올린 파일이 웹폰트보다
    우선"을 그 값으로 판단한다.
    """
    from .routers.files import _merged_weights, file_source_of, file_version_of
    return {
        "id": f.id,
        "name": f.name,
        "maker": f.maker or "",
        "stack": f.stack or "'Nanum Gothic',sans-serif",
        "has_file": bool(f.has_file),
        "is_english": bool(f.is_english),
        "webfont_family": f.webfont_family or None,
        "webfont_css_url": f.webfont_css_url or None,
        "file_source": file_source_of(f.id),
        "file_version": file_version_of(f.id),
        "available_weights": [w["weight"] for w in _merged_weights(f)],
    }


# ── 굵기 고르기 ──────────────────────────────────────────────────

def font_weights(font) -> list:
    from .routers.files import _merged_weights
    return [w["weight"] for w in _merged_weights(font)] or [int(font.primary_weight or 400)]


def pick_weight(font, target: int, cap: int = 900) -> int:
    """target에 가장 가까운 굵기를 고르되 cap을 넘지 않는다.

    cap 이하가 하나도 없으면 어쩔 수 없이 가진 것 중에서 고른다. 굵기를 하나만
    가진 폰트가 실제로 많다(Monoton·Anton·여기어때 잘난체는 800 하나뿐).
    그런 폰트를 배제하면 후보가 크게 줄고, 크기 차이가 위계를 거들어 준다.
    """
    ws = font_weights(font)
    pool = [w for w in ws if w <= cap] or ws
    return min(pool, key=lambda w: abs(w - target))


def generate(db, shape: str = "", script: str = "ko",
             locked: dict = None) -> dict:
    """제목 · 본문 두 폰트 한 벌.

    고른 모양은 **제목**에 걸린다. 본문은 언제나 고딕·명조에서 고른다 —
    손글씨나 장식체를 문단으로 깔면 읽히지 않기 때문이다.

    locked 에 담긴 슬롯은 그대로 두고 나머지만 다시 뽑는다. 상세페이지에서
    넘어올 때 그 폰트를 잠근 채로 들어오는 것이 이 경로다.
    """
    from .models import Font

    locked = locked or {}
    if script not in ("ko", "en", "mix"):
        script = "ko"
    cat = get_shape(shape)
    key = cat["key"]
    surprise = key == SURPRISE_KEY

    fonts = db.query(Font).all()
    by_id = {f.id: f for f in fonts}
    pcts = _percentiles(fonts)

    title_pool, text_pool = script_pools(script, fonts)
    if len(title_pool) < 1 or len(text_pool) < 2:
        title_pool, text_pool = script_pools("ko", fonts)

    fixed = {}
    used = set()
    for slot in ("title", "body"):
        f = by_id.get(locked.get(slot) or 0)
        if f is not None:
            fixed[slot] = f
            used.add(f.id)

    def pick(pool, target, extra=None, keep=None):
        """후보를 좁히지 않는다. 전부 점수를 매기고 확률로 뽑는다 —
        상위 N종으로 자르던 옛 방식이 다양성을 죽인 원인이었다.

        keep 은 '이 조건을 만족해야 후보'라는 뜻이다. 후보가 _MIN_POOL 도
        안 되면 조건을 푼다 — 걸러서 텅 비는 것보다 낫다.
        """
        cands = [f for f in pool if f.id not in used]
        if keep:
            narrowed = [f for f in cands if keep(f)]
            # 하나라도 남으면 조건을 지킨다. 아무것도 안 남을 때만 푼다 —
            # 걸러서 텅 비는 것보다는 조건을 어기는 편이 낫다.
            if narrowed:
                cands = narrowed
        if not cands:
            return None
        if surprise:
            return random.choice(cands)
        scored = []
        for f in cands:
            sc = _slot_score(f, pcts, target, {})
            if extra:
                sc += extra(f)
            if f.id in _RECENT:
                sc -= _RECENT_PENALTY
            scored.append((sc, f))
        return _weighted_pick(scored)

    # ── 제목 — 고른 모양에서 ─────────────────────────────────────
    t_font = fixed.get("title")
    if t_font is None:
        t_font = pick(title_pool, TITLE_TARGET.get(key, {"d": 0.6}),
                      keep=None if surprise else (lambda f: _in_shape(f, key)))
    if t_font is None:
        return {}
    used.add(t_font.id)

    # ── 본문 — 언제나 고딕·명조에서, 제목과 맞춰 ─────────────────
    #
    # 굵기 조건을 고르는 단계에 넣는다. 나중에 상한만 걸어서는 안 된다 —
    # pick_weight 는 상한 이하가 하나도 없으면 가진 것 중에서 고르기 때문이다.
    # 실제로 300 뿐인 손글씨 제목에 400 짜리 본문이 붙어 위계가 뒤집혔다.
    t_w = pick_weight(t_font, 700)

    def body_keep(f):
        if min(font_weights(f)) > t_w:
            return False
        return True if surprise else _body_ok(f)

    b_font = fixed.get("body")
    if b_font is None:
        b_font = pick(
            text_pool, BODY_TARGET,
            lambda f: _contrast(t_font, f, pcts) + _harmony(t_font, f, pcts),
            keep=body_keep)
    if b_font is None:
        return {}
    used.add(b_font.id)

    b_w = pick_weight(b_font, 300, cap=t_w)

    for fid in {t_font.id, b_font.id}:
        _RECENT.append(fid)

    return {
        "shape": key,
        "shape_label": cat["label"],
        "script": script,
        "fonts": {"title": font_brief(t_font), "body": font_brief(b_font)},
        "weights": {"title": t_w, "body": b_w},
        "samples": specimen(script),
    }


def top_fonts_for(db, shape: str, n: int = 8) -> list:
    """그 모양에서 제목으로 가장 잘 맞는 폰트 n종 (점수순, 무작위 없음).

    페이지 아래 소개 블록이 쓴다. 화면이 추천하는 것과 아래 목록이 서로 다른
    근거를 쓰면 같은 페이지에서 두 답이 어긋난다.
    """
    from .models import Font

    cat = get_shape(shape)
    key = cat["key"]
    if key == SURPRISE_KEY:
        # 고르는 기준 자체가 없는 자리다. 아무 순서나 실으면 "이게 추천인가"로
        # 읽히므로 목록을 내지 않는다.
        return []
    fonts = [f for f in db.query(Font).all()
             if not is_english(f) and _in_shape(f, key)]
    if not fonts:
        return []
    pcts = _percentiles(db.query(Font).all())
    target = TITLE_TARGET.get(key, {"d": 0.6})
    scored = [(_slot_score(f, pcts, target, {}), f) for f in fonts]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in scored[:n]]
