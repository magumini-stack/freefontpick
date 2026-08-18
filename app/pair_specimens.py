"""조합 페이지(/font-pair)의 카테고리 · 목업 · 견본 문구.

카테고리
--------
기존 조합 테마는 21종인데 고르라고 늘어놓기엔 너무 많고 서로 겹친다. 그렇다고
DB의 theme 값을 줄이면 저장된 1,272건과 문구뱅크가 전부 흔들린다.
그래서 **이 페이지에서만** 6개로 묶어 보여주고, 여기에 '뜻밖의 발견'을 더한다.
DB·문구뱅크·저장된 조합은 하나도 건드리지 않는다.

`themes`는 이제 화면 분류용 참고 값이다. 2차 개편에서 추천 엔진이
font_pair_engine.py로 독립하면서 저장 조합에서 학습하지 않게 됐다.

목업
----
견본을 추상적인 문서 한 장으로 그리지 않는다. 고른 카테고리의 **실제 틀** 안에
조판한다 — 썸네일 16:9, 카드뉴스 1:1, 명함, 세로 포스터, 카드, 매거진 지면.
폰트픽은 용도로 폰트를 골라주는 사이트라 카테고리와 그대로 이어지고,
"이 조합을 내 자리에 쓰면 어떻게 보이는가"를 바로 답해 준다.

견본 문구
--------
문구 길이는 **틀이 정한다.** 명함에 400자를 넣을 수 없고 매거진 지면에 100자로는
지면이 빈다. 그래서 카테고리마다 그 목업에 맞는 길이로 한글·영문 한 벌씩 쓴다.

카테고리마다 한 벌씩만 두는 이유: 문구가 고정돼 있어야 폰트만 바뀔 때 비교가
된다. 조합을 새로 뽑을 때마다 글까지 바뀌면 서체가 달라 보이는 건지 문장이
달라진 건지 알 수 없다. 사용자는 화면에서 직접 고쳐 쓸 수 있다.

영문 문구가 따로 있는 이유: 영문 전용 폰트에 한글 문구를 얹으면 글리프가 없어
통째로 깨진다.
"""

# key      : 내부 식별자 (주소 파라미터로도 쓰인다)
# label    : 화면 라벨
# desc     : 이 자리가 어떤 자리인지 한 줄 설명 (페이지 아래 소개 블록이 쓴다).
#            견본 문구를 설명 대신 쓰면 안 된다 — 그건 예시 문장이라 맥락 없이
#            보면 무슨 말인지 알 수 없다. 실제로 그렇게 넣었다가 걷어냈다.
# mockup   : 견본 틀 — static/font-pair.html의 .mk-{mockup} 이 그린다 (모두 가로형)
# themes   : 기존 21개 테마 중 이 카테고리가 아우르는 것 (분류 참고용)
# ko / en  : (타이틀, 서브타이틀, 본문) — 길이는 목업에 맞춰 다르다
PAIR_CATEGORIES = [
    {
        "key": "video",
        "desc": "작은 화면에서 흘끗 보고 읽혀야 하는 자리. 제목은 통이 크고 굵게, 자막은 담백하게 받칩니다.",
        "label": "영상 · 자막",
        "mockup": "thumb",          # 16:9 썸네일 — 큰 제목 + 아래 자막 바
        "themes": ["유튜브 썸네일", "브이로그 자막", "인스타 릴스 · 숏폼 자막"],
        "ko": (
            "이걸 몰라서\n3년을 버렸다",
            "구독자 1만 명이 가장 많이 물어본 것",
            "자막은 한 줄에 열두 자를 넘기지 않는 편이 읽힙니다.",
        ),
        "en": (
            "I Wasted\nThree Years",
            "What ten thousand subscribers ask most",
            "Keep each caption line under a dozen words.",
        ),
    },
    {
        "key": "sns",
        "desc": "손가락으로 넘기는 자리. 제목이 한 번에 잡히고 본문은 두 줄 안에서 끝나야 다음 장으로 넘어갑니다.",
        "label": "SNS · 카드뉴스",
        "mockup": "card",           # 가로 카드 — 따뜻한 모래색 바탕
        "themes": ["카드뉴스 · SNS", "이벤트 · 프로모션 배너"],
        "ko": (
            "한 장에 하나만",
            "넘기게 만드는 카드의 리듬",
            "카드뉴스는 손가락이 결정합니다. 한 장에 문장을 욱여넣으면 넘기기 전에 "
            "지치고, 너무 비우면 다음 장을 눌러야 할 이유가 사라집니다.",
        ),
        "en": (
            "One Idea Per Card",
            "The rhythm that keeps a thumb moving",
            "A deck is decided by the thumb. Cram a slide and the reader gives up "
            "before swiping; empty it and there is no reason to swipe at all.",
        ),
    },
    {
        "key": "brand",
        "desc": "유행보다 오래 남아야 하는 자리. 획의 대비가 과하지 않고 자간이 고른 서체가 명함부터 간판까지 견딥니다.",
        "label": "브랜딩 · 로고",
        "mockup": "namecard",       # 명함 비율(90×50) — 납작하고 아래로 붙는다
        "themes": [
            "명함 · 브랜드 로고", "감성 카페 · 브랜딩", "모던 미니멀 제목",
            "포인트 서체 조합", "영문 로고 · 캐치프레이즈",
        ],
        "ko": (
            "길목 서점",
            "오래 두고 읽는 책",
            "서울 마포구 연남로 12   ·   02-123-4567   ·   gilmok.kr",
        ),
        "en": (
            "Corner Books",
            "Slow reading, kept well",
            "12 Yeonnam-ro, Seoul   ·   +82 2 123 4567   ·   corner.kr",
        ),
    },
    {
        "key": "poster",
        "desc": "지나가면서, 대개는 비스듬히 보는 자리. 굵기보다 글자통의 크기가 읽히는 거리를 정합니다.",
        "label": "포스터 · 안내",
        "mockup": "poster",         # 가로 포스터 — 짙은 남색 바탕
        "themes": [
            "포스터 · 안내문", "시니어 친화 · 관공서", "큰 안내 본문",
            "굵은 산세리프 슬로건",
        ],
        "ko": (
            "겨울 정원 산책",
            "12월 6일 토요일 오후 2시 · 서울식물원",
            "안내문은 읽으려고 다가서는 글이 아닙니다. 지나가면서, 대개는 비스듬히, "
            "한 번에 봅니다. 그래서 굵기보다 글자통의 크기가 중요하고, 줄 사이가 "
            "좁으면 멀리서 한 덩어리로 뭉쳐 보입니다.",
        ),
        "en": (
            "A Walk in the Winter Garden",
            "Saturday, December 6 · 2 PM · Seoul Botanic Park",
            "Signage is not read by someone leaning in. It is caught in passing, "
            "usually at an angle, in a single look.",
        ),
    },
    {
        "key": "hand",
        "desc": "내용보다 필적이 먼저 닿는 자리. 반듯한 서체보다 조금 기울고 흔들리는 획이 오래 남습니다.",
        "label": "감성 · 손글씨",
        "mockup": "note",           # 가로 카드, 가운데 정렬
        "themes": ["캘리 · 손글씨 감성", "웨딩 · 청첩장", "키즈 · 교육 콘텐츠", "반려동물"],
        "ko": (
            "고맙습니다",
            "오래 기억하겠습니다",
            "어떤 문장은 내용보다 필적이 먼저 도착합니다. 한 번 읽고 오래 간직하는 "
            "글에서는, 반듯한 서체보다 조금 기울고 흔들리는 획이 더 오래 남습니다.",
        ),
        "en": (
            "Thank You",
            "We will remember this",
            "Some sentences land as handwriting before they land as meaning. On a note "
            "read once and kept for years, a stroke that leans and wavers outlasts a "
            "tidy one.",
        ),
    },
    {
        "key": "read",
        "desc": "오래 읽어도 지치지 않아야 하는 자리. 독자가 서체를 알아차리지 못하는 것이 목표입니다.",
        "label": "본문 · 읽기",
        "mockup": "magazine",       # 매거진 지면 — 2단 본문
        "themes": ["블로그 · 매거진 본문", "영문 본문 · 에디토리얼", "한글 + 영문 조합"],
        "ko": (
            "오래 읽어도 지치지 않게",
            "본문 서체가 하는 일은 사라지는 것",
            "좋은 본문 서체는 눈에 띄지 않습니다. 독자가 서체를 알아차렸다면 대개 "
            "무언가 불편했다는 뜻입니다. 글자 크기보다 줄 사이와 한 줄의 길이가 "
            "피로를 좌우합니다. 한 줄에 서른 자 안팎, 줄 사이는 글자 크기의 "
            "1.7배쯤이 무난합니다. 서체를 고르는 일은 결국 독자가 서체를 잊게 "
            "만드는 일입니다.",
        ),
        "en": (
            "Built for the Long Read",
            "The body face does its job by disappearing",
            "A good text face goes unnoticed. If a reader has noticed the type, "
            "something was usually getting in the way. Line spacing and measure "
            "decide fatigue more than size does. Around sixty-five characters to "
            "the line reads comfortably. Choosing a text face is the work of making "
            "the reader forget it.",
        ),
    },
    {
        # 어울림 계산을 끄고 무작위로 뽑는 자리. 목업과 문구는 다른 카테고리에서
        # 하나를 골라 빌려 쓴다 — 틀 없이 띄우면 무엇을 보는 화면인지 알 수 없다.
        "key": "surprise",
        "desc": "어울림 계산을 끄고 무작위로 셋을 붙이는 자리. 대부분은 어긋나지만, 가끔 규칙으로는 만나지 않았을 짝이 나옵니다.",
        "label": "뜻밖의 발견",
        "mockup": "",               # 비어 있으면 다른 카테고리에서 무작위로 빌린다
        "themes": [],
        "ko": (
            "계산에 없던 짝",
            "어울림은 자주 규칙 밖에 있습니다",
            "점수로 고르면 안전한 조합이 나옵니다. 그리고 안전한 것은 대체로 "
            "심심합니다. 여기서는 어울림 계산을 끄고 무작위로 셋을 붙여 봅니다.",
        ),
        "en": (
            "A Pair Nobody Calculated",
            "Good matches often sit outside the rules",
            "Scoring picks safe combinations, and safe is usually dull. Here the "
            "matching is switched off and three faces are thrown together at random.",
        ),
    },
]

# 처음 열었을 때 보여줄 자리. 포스터는 글자가 가장 크게 앉는 틀이라
# 폰트 모양이 한눈에 들어온다.
DEFAULT_CATEGORY = "poster"
SURPRISE_CATEGORY = "surprise"

_BY_KEY = {c["key"]: c for c in PAIR_CATEGORIES}
_WITH_MOCKUP = [c for c in PAIR_CATEGORIES if c["mockup"]]


def get_category(key: str) -> dict:
    """키로 카테고리를 찾는다. 모르는 키면 기본값으로 떨어진다 —
    주소를 손으로 고쳐 들어오는 경우가 있으므로 예외를 던지지 않는다."""
    return _BY_KEY.get(key or "") or _BY_KEY[DEFAULT_CATEGORY]


def themes_of(key: str) -> list:
    """그 카테고리가 아우르는 기존 theme 목록 (분류 참고용)."""
    return list(get_category(key)["themes"])


def specimen(key: str, script: str = "ko", borrow: str = "") -> dict:
    """견본 한 벌 — 목업 이름과 세 줄.

    script는 'ko' | 'en' | 'mix'. mix는 제목만 영문으로 두고 나머지를 한글로 둔다
    — 한글 화면에 영문 제목을 얹는 것이 실제로 가장 흔한 혼용 방식이다.

    '뜻밖의 발견'처럼 mockup이 비어 있으면 다른 카테고리의 틀과 문구를 빌린다.
    borrow로 어느 것을 빌릴지 지정할 수 있다 — 주소로 같은 화면을 재현하려면
    어느 틀을 빌렸는지도 함께 알아야 하기 때문이다.
    """
    import random

    c = get_category(key)
    if not c["mockup"]:
        src = _BY_KEY.get(borrow or "")
        if src is None or not src.get("mockup"):
            src = random.choice(_WITH_MOCKUP)
        c = src

    ko, en = c["ko"], c["en"]
    if script == "en":
        t, s, b = en
    elif script == "mix":
        t, s, b = en[0], ko[1], ko[2]
    else:
        t, s, b = ko
    return {"mockup": c["mockup"], "borrowed": c["key"],
            "title": t, "subtitle": s, "body": b}
