"""조합 페이지(/font-pair)의 모양 분류와 견본 문구.

2026-08 개편 — '용도로 셋'에서 '모양으로 둘'로
--------------------------------------------
예전에는 영상·자막 / 카드뉴스 / 브랜딩처럼 **쓰는 자리**로 나누고 제목·부제·
본문 세 폰트를 얹었다. 두 가지가 어긋났다.

  1. 자리를 고르는 일과 폰트를 고르는 일이 섞였다. 같은 고딕이라도 자리마다
     다른 짝이 붙어서, "이 폰트에 무엇을 붙이지"라는 물음에는 답하지 못했다.
  2. 세 자리는 한눈에 판단하기에 많다. 제목과 본문의 관계만 남기면 짝이 맞는지
     아닌지가 바로 보인다.

그래서 **모양**으로 나누고 **두 폰트**만 맞춘다. 고딕을 고르면 고딕 제목에
어울리는 본문이 붙는다. 상세페이지에서 넘어오면 그 폰트의 모양으로 들어온다.

모양은 무엇으로 나누나
--------------------
폰트마다 이미 붙어 있는 태그를 묶었다. 새 기준을 만들지 않은 이유는, 태그가
어드민에서 관리되는 값이라 폰트를 추가하면 분류도 저절로 따라오기 때문이다.
한 폰트가 두 계열에 걸치는 경우가 34종 있는데(예: 귀여운 + 디스플레이)
그대로 둔다 — 실제로 두 성격을 겸하는 폰트다.

견본 문구는 계열마다 다르다
------------------------
한 벌로 통일해 봤는데, 계열마다 글이 놓이는 자리가 달라서 맞지 않았다. 손글씨나
귀여운 글자는 실제로 짧은 말에 쓰인다 — 카드 한 줄, 인사 한 마디다. 거기에 세
줄짜리 설명문을 깔면 그 폰트가 잘 하는 일을 못 보여준다. 디스플레이는 반대로
썸네일처럼 크고 짧게 쓰는 자리다.

비교가 흔들리지는 않는다. **문구는 계열 안에서 고정**이라, 조합을 다시 뽑아도
글은 그대로고 폰트만 바뀐다. 계열을 옮길 때만 글이 함께 바뀌는데, 그건 보러 온
자리가 달라진 것이라 같이 바뀌는 편이 맞다. 화면에서 직접 고쳐 쓸 수도 있다.
"""

# key   : 내부 식별자 (주소 파라미터로도 쓴다)
# label : 화면 라벨
# desc  : 이 계열이 어떤 글자인지 한 줄. 칩 아래와 페이지 아래 소개가 함께 쓴다.
# tags  : 이 계열로 묶는 태그. 폰트에 이 중 하나라도 있으면 이 계열이다.
# ko/en : 이 계열의 견본 (제목, 본문). 본문 안의 줄바꿈 문자는 화면에서
#         그대로 줄바꿈으로 그려진다 (.fp-text 가 white-space:pre-line).
SHAPES = [
    {
        "key": "gothic",
        "label": "고딕",
        "desc": "획의 굵기가 고르고 장식이 없는 계열입니다. "
                "제목에도 본문에도 무난하게 놓여서 가장 많이 쓰입니다.",
        "tags": {"제목-본문용 고딕", "네모틀 고딕", "제목용 굴림", "UI/UX/Web"},
        # 가장 무난한 자리라 견본도 일반적인 글로 둔다. 다른 계열과 견줄 때의
        # 기준이 되는 문구다.
        "ko": ("같은 문장, 다른 목소리",
               "제목이 눈길을 잡고 본문이 그 눈길을 붙듭니다. 둘의 결이 너무 "
               "닮으면 어디부터 읽어야 할지 알기 어렵고, 너무 다르면 서로를 "
               "잡아먹습니다. 굵기와 크기로 차이를 주고 개성은 한쪽에만 두는 "
               "편이 안전합니다."),
        "en": ("One Voice, Two Roles",
               "A headline catches the eye and the text keeps it. When the two "
               "look too much alike the reader cannot tell where to begin; when "
               "they clash they fight for the same attention. Set them apart by "
               "weight and size, and let only one of them carry the personality."),
    },
    {
        "key": "serif",
        "label": "명조 · 세리프",
        "desc": "획 끝에 맺음이 있고 가로세로 굵기 차이가 있는 계열입니다. "
                "길게 읽는 글과 격식 있는 자리에 어울립니다.",
        "tags": {"부드러운 명조", "독특한 세리프"},
        # 길게 읽는 자리다. 본문을 넉넉히 두어 여러 줄이 쌓였을 때를 보여준다.
        "ko": ("오래 읽어도 지치지 않는 글",
               "명조는 획 끝에 작은 맺음을 답니다. 그 맺음이 시선을 다음 글자로 "
               "넘겨 주어, 긴 글을 읽을 때 눈이 덜 지칩니다. 책과 신문이 오래도록 "
               "이 계열을 써 온 이유입니다."),
        "en": ("Made for Long Reading",
               "A serif finishes each stroke with a small flag. Those flags pass "
               "the eye along to the next letter, which is why books and "
               "newspapers have set long text this way for centuries."),
    },
    {
        "key": "hand",
        "label": "손글씨",
        "desc": "사람이 쓴 획이 그대로 남은 계열입니다. 개성이 강해 한 자리에만 "
                "두고 나머지는 받쳐 주는 편이 안전합니다.",
        "tags": {"손글씨", "캘리그라피"},
        # 짧게. 손글씨가 실제로 놓이는 자리는 카드 한 줄, 인사 한 마디다.
        # 그래도 본문은 세 줄은 둔다 — 손글씨는 글자마다 모양이 미묘하게 달라서
        # 여러 줄이 쌓여야 그 결이 보인다. 줄바꿈은 문장 단위로 직접 넣는다
        # (화면이 pre-line 으로 그린다).
        "ko": ("오늘도 잘 지냈나요",
               "손으로 쓴 글씨에는 속도와 힘이 남습니다.\n"
               "같은 글자를 두 번 써도 모양이 조금씩 다르고,\n"
               "그 어긋남이 사람 손의 흔적으로 읽힙니다."),
        "en": ("Hope your day went well",
               "Handwriting keeps the speed and pressure of the hand.\n"
               "Write the same letter twice and it comes out\n"
               "a little different — that drift reads as a person."),
    },
    {
        "key": "display",
        "label": "디스플레이 · 장식",
        "desc": "크게 썼을 때를 염두에 두고 만든 계열입니다. 제목에서 힘을 내지만 "
                "문단으로 깔면 읽기 어려워집니다.",
        "tags": {"디스플레이", "장식", "시선을 끄는 제목용"},
        # 유튜브 썸네일 자리. 두 줄 제목에 짧은 덧말 하나 — 실제로 그렇게 쓴다.
        "ko": ("이 폰트 하나면\n끝납니다",
               "무료 · 상업용 가능 · 5분 정리"),
        "en": ("One Font\nDoes It All",
               "Free · Commercial use · 5 minutes"),
    },
    {
        "key": "cute",
        "label": "귀여운 · 펜시",
        "desc": "둥글고 말랑한 인상의 계열입니다. 대상이 뚜렷한 자리에 맞고 "
                "격식 있는 문서와는 잘 맞지 않습니다.",
        "tags": {"귀여운", "펜시"},
        # 대상이 뚜렷하고 말이 짧은 자리다. 그래도 본문은 세 줄은 되어야 한다 —
        # 한 줄로는 이 폰트를 문단으로 깔았을 때의 결이 안 보인다.
        "ko": ("말랑말랑 오늘의 기분",
               "작고 둥근 글자는 짧은 말에 어울립니다.\n"
               "길게 늘어놓으면 금세 무거워지니\n"
               "한두 줄로 끊어 주는 편이 좋습니다."),
        "en": ("A Soft Little Mood",
               "Round letters suit short and friendly lines.\n"
               "Stretch them into a long paragraph and they\n"
               "grow heavy, so keep it to a line or two."),
    },
]

# 본문에는 절대 안 쓰는 태그. 계열이 무엇이든 이 성격을 겸하면 뺀다.
#
# 크게 썼을 때를 전제로 만든 글자와, 획이 이어져 흘려 쓴 글자다. 둘 다 문단
# 크기로 내려오면 글자 사이가 엉겨 읽히지 않는다 — 매거진 '조합 만드는 법'의
# 3번이 그 이야기다. 손글씨는 여기 없다. 또박또박 쓴 손글씨는 짧은 문단에서
# 읽힌다.
BODY_NEVER = {"디스플레이", "장식", "시선을 끄는 제목용", "캘리그라피"}

# 제목 모양마다 본문으로 허용하는 계열.
#
# 처음에는 제목이 무엇이든 본문을 고딕·명조로 고정했다. 안전하지만, 손글씨
# 제목에 늘 같은 고딕이 붙으니 이 화면이 보여줄 수 있는 폭이 실제보다 좁아
# 보였다. 개성 있는 제목을 고른 사람은 본문도 그 결에 맞는 것을 찾는다.
#
# 그래서 고딕·명조 제목은 그대로 두고 — 고딕 제목에 손글씨 본문이 붙으면
# 고른 것이 아니라 잘못 붙은 것으로 읽힌다 — 손글씨·디스플레이·귀여운
# 제목에만 손글씨와 귀여운 계열을 본문 후보로 연다. 후보가 71종에서
# 124종으로 늘고, 그중 43%가 고딕·명조 밖이다.
BODY_SHAPES_BY_TITLE = {
    "gothic":  ("gothic", "serif"),
    "serif":   ("gothic", "serif"),
    "hand":    ("gothic", "serif", "hand", "cute"),
    "display": ("gothic", "serif", "hand", "cute"),
    "cute":    ("gothic", "serif", "cute", "hand"),
}

# 모르는 모양으로 들어왔을 때의 본문 후보.
BODY_SHAPES = ("gothic", "serif")

SURPRISE = {
    "key": "surprise",
    "label": "뜻밖의 발견",
    "desc": "어울림 계산을 끄고 아무거나 붙여 보는 자리입니다. 대부분은 어긋나지만, "
            "가끔 규칙으로는 만나지 않았을 짝이 나옵니다.",
    "tags": set(),
    "ko": ("어울릴 리 없는 둘",
           "규칙을 끄고 아무거나 붙였습니다. 대개는 어긋나지만, "
           "가끔 계산으로는 만나지 않았을 짝이 나옵니다."),
    "en": ("Two That Should Not Match",
           "The rules are off here. Most of these clash, but now and then a "
           "pair turns up that no calculation would have found."),
}

# 처음 열었을 때. 고딕으로 둔다 — 가장 많이 쓰는 계열이고, 여기서 시작하면
# 다른 계열로 옮겨 가며 비교하기 쉽다.
#
# ⚠ static/font-pair.html 의 DEFAULT_CAT 과 반드시 같아야 한다.
DEFAULT_SHAPE = "gothic"
SURPRISE_KEY = "surprise"

ALL_SHAPES = SHAPES + [SURPRISE]
_BY_KEY = {c["key"]: c for c in ALL_SHAPES}

# ── 견본 문구 ────────────────────────────────────────────────────
#
# 계열마다 SHAPES 안에 (제목, 본문) 으로 들어 있다. 여기 따로 표를 두지 않는
# 이유는, 문구가 그 계열의 성격에서 나오기 때문이다 — 계열을 고치면서 문구를
# 그대로 두면 어긋나는데, 한 자리에 있으면 눈에 걸린다.
DEFAULT_SAMPLE = {
    "ko": ("같은 문장, 다른 목소리",
           "제목이 눈길을 잡고 본문이 그 눈길을 붙듭니다. 굵기와 크기로 차이를 "
           "주고 개성은 한쪽에만 두는 편이 안전합니다."),
    "en": ("One Voice, Two Roles",
           "A headline catches the eye and the text keeps it. Set them apart by "
           "weight and size, and let only one carry the personality."),
}


def get_shape(key: str) -> dict:
    """키로 모양을 찾는다. 모르는 키면 기본값으로 떨어진다 —
    주소를 손으로 고쳐 들어오는 경우가 있으므로 예외를 던지지 않는다."""
    return _BY_KEY.get(key or "") or _BY_KEY[DEFAULT_SHAPE]


def shape_of_tags(names) -> str:
    """이 태그를 가진 폰트가 어느 모양인가. 상세페이지에서 넘어올 때 쓴다.

    두 계열에 걸치면 SHAPES 에 적은 순서가 이긴다 — 앞쪽이 더 좁고 뚜렷한
    분류라 '고딕이면서 디스플레이'인 폰트는 고딕으로 읽는 편이 맞다.
    """
    s = set(names or ())
    for c in SHAPES:
        if s & c["tags"]:
            return c["key"]
    return DEFAULT_SHAPE


def specimen(script: str = "ko", shape: str = "") -> dict:
    """그 계열의 견본 한 벌 — 제목과 본문.

    script 는 'ko' | 'en' | 'mix'. mix 는 제목만 영문으로 둔다 — 한글 화면에
    영문 제목을 얹는 것이 실제로 가장 흔한 혼용 방식이다.
    """
    c = get_shape(shape)
    ko = c.get("ko") or DEFAULT_SAMPLE["ko"]
    en = c.get("en") or DEFAULT_SAMPLE["en"]
    if script == "en":
        t, b = en
    elif script == "mix":
        t, b = en[0], ko[1]
    else:
        t, b = ko
    return {"title": t, "body": b}
