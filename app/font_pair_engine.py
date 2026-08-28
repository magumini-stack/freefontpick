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

카테고리마다 슬롯이 원하는 **백분위 목표**를 손으로 적어 둔다(아래 PROFILES).
절대값이 아니라 백분위라, 폰트가 늘거나 측정 기준이 바뀌어도 뜻이 유지된다.
"""
import math
import random
from collections import deque

from .font_metrics import metrics_of
from .pair_specimens import get_category, specimen

# ── 카테고리별 슬롯 목표 ──────────────────────────────────────────
#
# d/w/x는 **백분위 목표**(0=가장 가는 쪽, 1=가장 굵은 쪽)다. 적지 않은 축은
# 점수에 넣지 않는다 — 굳이 상관없는 자리까지 묶으면 후보만 좁아진다.
#
# tags/usage는 있으면 가산점(없다고 감점하지 않는다). 메타 채움률이 고르지
# 않아서(industry 53%, personality 66%) 필수 조건으로 쓰면 절반이 탈락한다.
PROFILES = {
    "video": {   # 썸네일·자막 — 작게 줄여도 버티게 굵고 넓게
        "title": {"d": 0.85, "w": 0.70},
        "subtitle": {"d": 0.55},
        "body": {"d": 0.45},
        "tags": {"유튜브 썸네일 추천": 2.0, "브이로그 자막용": 2.0,
                 "시선을 끄는 제목용": 1.5, "네모틀 고딕": 1.0},
        "usage": {"썸네일": 1.5, "영상자막": 1.5, "제목": 1.0},
    },
    "sns": {     # 카드뉴스 — 제목은 또렷하게, 본문은 편하게
        "title": {"d": 0.75, "w": 0.60},
        "subtitle": {"d": 0.50},
        "body": {"d": 0.38},
        "tags": {"카드뉴스용": 2.0, "시선을 끄는 제목용": 1.2, "귀여운": 0.8},
        "usage": {"SNS카드": 1.5, "캐치프레이즈": 1.0, "제목": 0.8},
    },
    "brand": {   # 명함·로고 — 과한 굵기보다 자형의 절제
        "title": {"d": 0.55, "w": 0.45},
        "subtitle": {"d": 0.35},
        "body": {"d": 0.30},
        "tags": {"로고디자인": 2.0, "독특한 세리프": 1.2, "부드러운 명조": 1.0,
                 "디자인 영어": 0.8},
        "usage": {"로고": 1.5, "패키지": 1.0, "캐치프레이즈": 0.8},
    },
    "poster": {  # 안내문 — 멀리서 읽히는 것이 전부
        "title": {"d": 0.80, "w": 0.75},
        "subtitle": {"d": 0.50},
        "body": {"d": 0.45, "x": 0.65},
        "tags": {"네모틀 고딕": 1.5, "제목-본문용 고딕": 1.5, "시선을 끄는 제목용": 1.2},
        "usage": {"포스터": 1.5, "정보전달": 1.2, "제목": 0.8},
    },
    "hand": {    # 감성·손글씨 — 굵기보다 필적
        "title": {"d": 0.45},
        "subtitle": {"d": 0.35},
        "body": {"d": 0.30},
        "tags": {"손글씨": 2.5, "캘리그라피": 2.0, "귀여운": 1.2, "펜시": 0.8},
        "usage": {"SNS카드": 0.8, "제목": 0.5},
        # 이 자리에는 고딕을 내보내지 않는다.
        #
        # 가산점만 주던 때는 실측 40회에서 서브·본문의 25회가 고딕이었다.
        # 이유가 있다 — 서브와 본문은 한 집안으로 묶여 '굵기 2개 이상'을
        # 요구하는데, 손글씨 계열 중 굵기가 여럿인 폰트는 13종뿐이라 그
        # 자리를 고딕 가족(아리따 돋움·원티드산스·나눔스퀘어…)이 채웠다.
        # 고딕을 빼도 굵기 2개 이상인 후보가 40종 남는다(명조·세리프·
        # 디스플레이·손글씨). 후보가 마르지 않으므로 아예 뺀다.
        "exclude": {"제목-본문용 고딕", "네모틀 고딕", "제목용 굴림"},
        # 제목은 반드시 손글씨 계열에서 고른다. 이 자리의 이름이 그것이다.
        # 가산점만으로는 40회 중 10회가 다른 계열이었다. 후보 69종.
        "require_slot": {"title": {"손글씨", "캘리그라피", "귀여운", "펜시"}},
    },
    "read": {    # 본문 — 오래 읽어도 지치지 않게
        "title": {"d": 0.60},
        "subtitle": {"d": 0.42},
        "body": {"d": 0.35, "x": 0.60},
        "tags": {"부드러운 명조": 2.2, "제목-본문용 고딕": 1.8, "네모틀 고딕": 1.5,
                 "UI/UX/Web": 1.2, "제목용 굴림": 0.8},
        "usage": {"본문": 2.0, "출판": 1.2, "정보전달": 1.0},
        # 오래 읽는 자리라 손글씨·장식 계열은 아예 후보에서 뺀다. 가산점을 안
        # 주는 것만으로는 부족했다 — 점수가 낮아도 확률 추출이라 결국 나온다.
        "exclude": {"손글씨", "캘리그라피", "펜시", "장식", "귀여운"},
        # 서브타이틀과 본문은 제목보다 더 좁게 본다. 디스플레이 서체는 표제로는
        # 쓰지만 문단으로 깔면 읽히지 않는다.
        "exclude_slot": {
            "subtitle": {"디스플레이", "시선을 끄는 제목용"},
            "body": {"디스플레이", "시선을 끄는 제목용"},
        },
    },
}

# 후보를 이만큼도 못 남기면 거르지 않는다. 걸러서 텅 비는 것보다 낫다.
_MIN_POOL = 8


def _allowed(font, cat_prof, slot) -> bool:
    """이 카테고리·슬롯에서 쓸 수 있는 폰트인가.

    exclude / exclude_slot 은 '빼는' 조건이고, require_slot 은 '있어야만
    쓰는' 조건이다. 가산점만으로는 부족한 자리가 있어서 뒤엣것을 더했다 —
    점수를 아무리 줘도 확률 추출이라 결국 다른 계열이 섞여 나온다.
    """
    names = {t.name for t in (font.tags or [])}

    need = set((cat_prof.get("require_slot") or {}).get(slot) or ())
    if need and not (names & need):
        return False

    ban = set(cat_prof.get("exclude") or ())
    ban |= set((cat_prof.get("exclude_slot") or {}).get(slot) or ())
    return not (names & ban)

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


# ── 한 집안으로 묶는 두 슬롯 ─────────────────────────────────────
#
# 매거진 '폰트 조합 만드는 법' 5번은 "굵기가 여러 개인 폰트 하나를 골라 제목에
# 굵은 것, 본문에 가는 것을 쓰는 것이 가장 실패가 적다"고 쓴다. 그런데 이 도구는
# 늘 서로 다른 셋을 내놨다. 우리 글과 도구가 서로 다른 말을 하고 있었다.
#
# 자리마다 묶는 짝이 다른 이유는 그 자리에서 개성을 맡는 슬롯이 다르기 때문이다.
# 손글씨 자리는 제목이 개성을 맡으니 서브·본문을 한 집안으로 묶어 받치고,
# 읽는 자리는 본문이 주인공이라 제목·서브를 묶는다.
#
# 결과는 늘 '두 서체'다. 셋을 다 다르게 두는 것은 '뜻밖의 발견'뿐이다.
FAMILY_PAIRS = {
    "video": ("subtitle", "body"),
    "sns": ("title", "subtitle"),
    "brand": ("title", "subtitle"),
    "poster": ("subtitle", "body"),
    "hand": ("subtitle", "body"),
    "read": ("title", "subtitle"),
    # "surprise" 는 없다 — 어울림 계산을 끄는 자리라 묶을 근거도 없다.
}


def _multi(font, cap: int = 900) -> bool:
    """cap 이하에서 서로 다른 굵기를 둘 이상 갖고 있나.

    한 폰트로 두 자리를 채우는데 굵기까지 같으면 위계가 없다. 화면에는 같은
    이름이 두 번 뜨고 글자도 똑같아서 '고장 났나'로 읽힌다.
    """
    return len({w for w in font_weights(font) if w <= cap}) >= 2


def _family_weights(font, hi_target: int, lo_target: int, cap: int = 900):
    """한 폰트에서 서로 다른 두 굵기를 고른다 — 굵은 쪽, 가는 쪽.

    hi_target 에 가장 가까운 것을 먼저 잡는데, 그게 하필 가진 것 중 가장 가벼운
    굵기면 아래가 없어진다(예: 400·900만 있는 폰트에서 500을 노리면 400이 잡힌다).
    그때는 굵은 쪽을 맨 위로 올려 아래를 만든다.
    """
    ws = sorted({w for w in font_weights(font) if w <= cap})
    if len(ws) < 2:
        w = pick_weight(font, hi_target, cap=cap)
        return w, w
    hi = min(ws, key=lambda w: abs(w - hi_target))
    lower = [w for w in ws if w < hi]
    if not lower:
        hi = ws[-1]
        lower = ws[:-1]
    return hi, min(lower, key=lambda w: abs(w - lo_target))


def generate(db, category: str, script: str = "ko",
             locked: dict = None, borrow: str = "") -> dict:
    """타이틀·서브타이틀·본문 한 벌.

    자리마다 두 슬롯은 같은 폰트의 다른 굵기로 묶는다(FAMILY_PAIRS). 그래서
    보통은 서체 두 벌이 나온다. 셋을 다 다르게 두는 것은 '뜻밖의 발견'뿐이다.

    locked에 담긴 슬롯은 그대로 두고 나머지만 다시 뽑는다. 사용자가 고정한
    것이 언제나 이긴다 — 가장 먼저 used에 들어가기 때문이다.
    """
    from .models import Font

    locked = locked or {}
    if script not in ("ko", "en", "mix"):
        script = "ko"
    cat = get_category(category)
    key = cat["key"]
    surprise = key == "surprise"
    prof = PROFILES.get(key, {})

    fonts = db.query(Font).all()
    by_id = {f.id: f for f in fonts}
    pcts = _percentiles(fonts)

    title_pool, text_pool = script_pools(script, fonts)
    if len(title_pool) < 1 or len(text_pool) < 2:
        title_pool, text_pool = script_pools("ko", fonts)

    used = set()
    fixed = {}
    for slot in ("title", "subtitle", "body"):
        f = by_id.get(locked.get(slot) or 0)
        if f is not None:
            fixed[slot] = f
            used.add(f.id)

    def pick(pool, slot, extra=None, require=None):
        """후보를 좁히지 않는다. 전부 점수를 매기고 확률로 뽑는다 —
        상위 N종으로 자르던 옛 방식이 다양성을 죽인 원인이었다.

        require 는 '한 집안'을 맡을 폰트를 고를 때만 쓴다(굵기가 둘 이상).
        """
        cands = [f for f in pool if f.id not in used]
        if require:
            # 한 집안을 맡을 폰트를 고르는 길이다. 여기서는 카테고리 계열
            # 조건(_allowed)을 양보하지 않는다 — 후보가 모자라면 '한 집안'을
            # 포기하는 편이, 감성·손글씨 자리에 고딕이 끼는 것보다 낫다.
            # 비면 None 을 돌려주고 generate 가 묶지 않는 길로 되돌아간다.
            cands = [f for f in cands if require(f) and _allowed(f, prof, slot)]
            if not cands:
                return None
        else:
            if not cands:
                return None
            # 여기서는 후보가 너무 줄면 거르지 않는다 — 걸러서 텅 비는 것보다 낫다.
            keep = [f for f in cands if _allowed(f, prof, slot)]
            if len(keep) >= _MIN_POOL:
                cands = keep
        if surprise:
            return random.choice(cands)
        scored = []
        for f in cands:
            s = _slot_score(f, pcts, prof.get(slot, {}), prof)
            if extra:
                s += extra(f)
            if f.id in _RECENT:
                s -= _RECENT_PENALTY
            scored.append((s, f))
        return _weighted_pick(scored)

    # ── 이번 판에서 한 집안으로 묶을 두 슬롯 ──────────────────────
    pair = None if surprise else FAMILY_PAIRS.get(key)
    if pair:
        a, b = pair
        if a in fixed and b in fixed and fixed[a].id != fixed[b].id:
            # 사용자가 두 자리를 서로 다른 폰트로 고정했다. 고정한 것이 이긴다.
            pair = None
        elif script == "mix" and "title" in pair:
            # 섞어 쓰기는 제목을 영문에서, 나머지를 한글에서 뽑는다. 한 폰트가
            # 양쪽 후보군에 다 있을 수 없으므로 제목이 낀 짝은 묶지 못한다.
            pair = None
        else:
            lead_pool = title_pool if a == "title" else text_pool
            if len([f for f in lead_pool if _multi(f)]) < _MIN_POOL:
                # 굵기 여러 개인 후보가 이만큼도 없으면 묶어도 위계가 안 나온다.
                pair = None

    head_family = bool(pair) and pair[0] == "title"

    # ── 제목 ─────────────────────────────────────────────────────
    t_font = fixed.get("title") or (fixed.get("subtitle") if head_family else None)
    if t_font is None:
        t_font = pick(title_pool, "title", require=_multi if head_family else None)
    if t_font is None:
        return {}
    if head_family and not _multi(t_font):
        pair = head_family = None   # 고정된 폰트가 굵기 하나뿐이면 못 묶는다
    used.add(t_font.id)

    # 제목·서브가 한 집안이면 둘의 굵기를 여기서 먼저 정한다. 본문이 넘지 말아야
    # 할 선이 제목(t_w)이 아니라 서브(s_w)라서, 그 값을 알아야 아래 후보를
    # 제대로 거를 수 있다. 나중에 정하면 상한만 걸리고 후보는 안 걸러져,
    # 본문이 서브보다 굵게 나오는 판이 생긴다 — 실제로 그랬다.
    s_w = None
    if head_family:
        t_w, s_w = _family_weights(t_font, 700, 500)
    else:
        t_w = pick_weight(t_font, 700)

    # 서브·본문은 제목보다 굵으면 안 된다. 굵기를 나중에 깎는 것만으로는 부족하다
    # — 굵기를 하나만 가진 폰트가 있어 상한을 걸어도 그 값이 나온다. 고르는
    # 단계에서 거른다. 후보가 너무 줄면 되돌린다(위계보다 조합이 안 나오는 쪽이
    # 더 나쁘고, 크기 차이가 위계를 거들어 준다).
    ceiling = s_w if head_family else t_w
    fit = [f for f in text_pool if min(font_weights(f)) <= ceiling]
    if len(fit) >= 12:
        text_pool = fit

    s_font = b_font = None

    if head_family:
        # 제목·서브가 한 집안. 본문만 다른 집안에서 고른다.
        s_font = t_font
        b_font = fixed.get("body") or pick(
            text_pool, "body",
            lambda f: _contrast(t_font, f, pcts) + _harmony(t_font, f, pcts))
    elif pair:
        # 서브·본문이 한 집안. 제목이 개성을 맡고 나머지를 한 집안이 받친다.
        fam = fixed.get("subtitle") or fixed.get("body")
        if fam is not None and not _multi(fam, t_w):
            fam, pair = None, None
        if pair and fam is None:
            fam = pick(text_pool, "body",
                       lambda f: _contrast(t_font, f, pcts) + _harmony(t_font, f, pcts),
                       require=lambda f: _multi(f, t_w))
        if fam is None:
            pair = None
        else:
            s_font = b_font = fam
            used.add(fam.id)

    if not pair:
        # 묶지 않는 자리(뜻밖의 발견)거나, 묶으려다 후보가 없어 물러선 경우.
        b_font = b_font or fixed.get("body") or pick(
            text_pool, "body",
            lambda f: _contrast(t_font, f, pcts) + _harmony(t_font, f, pcts))
        if b_font is None:
            return {}
        used.add(b_font.id)
        # 서브타이틀은 제목과 본문 사이에 놓인다. 셋이 전부 다른 결이면
        # 산만해지므로 이미 뽑힌 둘과 닮은 쪽을 우선한다.
        s_font = fixed.get("subtitle") or pick(
            text_pool, "subtitle",
            lambda f: (_harmony(t_font, f, pcts) + _harmony(b_font, f, pcts)) * 0.6)
        if s_font is None:
            s_font = pick(text_pool, "subtitle")

    if s_font is None or b_font is None:
        return {}
    if b_font.id not in used:
        used.add(b_font.id)

    # ── 굵기 ─────────────────────────────────────────────────────
    if head_family:
        # t_w · s_w 는 위에서 이미 정했다(같은 폰트라 굵기까지 같으면 위계가
        # 없으므로 _family_weights 가 반드시 다른 값을 준다).
        b_w = pick_weight(b_font, 300, cap=s_w)
    elif pair:
        s_w, b_w = _family_weights(s_font, 500, 300, cap=t_w)
    else:
        # 본문은 300이 있으면 300으로 간다. 오래 읽는 글은 한 단 가볍게 앉는 쪽이
        # 덜 지친다 — 400만 있는 폰트는 pick_weight가 알아서 400을 준다.
        b_w = pick_weight(b_font, 300, cap=t_w)
        s_w = pick_weight(s_font, max(b_w, min(t_w, 500)), cap=max(t_w, b_w))
        if s_w < b_w:
            s_w = pick_weight(s_font, b_w, cap=max(t_w, b_w))

    for fid in {t_font.id, s_font.id, b_font.id}:
        _RECENT.append(fid)

    return {
        "category": key,
        "category_label": cat["label"],
        "script": script,
        # 어느 두 슬롯이 한 집안인지 — 화면이 같은 이름을 두 번 보여줄 때
        # "왜 똑같지"가 아니라 "일부러 묶은 것"으로 읽히게 하려면 필요하다.
        "family": list(pair) if pair else [],
        "fonts": {"title": font_brief(t_font), "subtitle": font_brief(s_font),
                  "body": font_brief(b_font)},
        "weights": {"title": t_w, "subtitle": s_w, "body": b_w},
        "samples": specimen(key, script, borrow=borrow),
    }


def top_fonts_for(db, category: str, n: int = 8) -> list:
    """그 카테고리에 가장 잘 맞는 폰트 n종 (점수순, 무작위 없음).

    페이지 아래 소개 블록이 쓴다. 저장된 조합에서 뽑던 것을 이걸로 바꾼다 —
    화면이 추천하는 것과 아래 목록이 서로 다른 근거를 쓰면, 같은 페이지에서
    두 답이 어긋난다. 실제로 '브랜딩 · 로고' 아래에 손글씨체가 실려 있었다.
    """
    from .models import Font

    cat = get_category(category)
    prof = PROFILES.get(cat["key"])
    if not prof:
        # '뜻밖의 발견'은 고르는 기준 자체가 없다. 점수가 전부 같아 정렬이
        # 무의미하므로 목록을 내지 않는다 — 아무 순서나 실으면 "이게 추천인가"로
        # 읽힌다.
        return []
    fonts = [f for f in db.query(Font).all() if not is_english(f)]
    if not fonts:
        return []
    pcts = _percentiles(fonts)
    scored = [(_slot_score(f, pcts, prof.get("title", {}), prof), f) for f in fonts]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in scored[:n]]
