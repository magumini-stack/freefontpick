"""조합 페이지(/font-pair)의 카테고리와 견본 문구.

카테고리
--------
기존 조합 테마는 21종인데 고르라고 늘어놓기엔 너무 많고 서로 겹친다. 그렇다고
DB의 theme 값을 줄이면 저장된 1,272건과 문구뱅크가 전부 흔들린다.
그래서 **이 페이지에서만** 21종을 6개로 묶어 보여준다. 아래 표가 전부이고,
DB·문구뱅크·저장된 조합은 하나도 건드리지 않는다.

견본 문구
--------
기존 THEME_PHRASE_BANK를 쓰지 않는다. 그 뱅크는 (제목, 본문) **2문구 쌍**이라
서브타이틀 자리를 다른 쌍에서 빌려와야 하는데, 그러면 세 줄이 한 덩어리로
읽히지 않는다. 본문도 중앙값 21자라 2단 캔버스를 못 채운다.
그 문구들은 작은 조합 카드용으로 잘 쓰인 것이고, 큰 견본 캔버스는 다른 일이다.

카테고리마다 **한 벌씩만** 둔다. 문구가 고정돼 있어야 폰트만 바뀔 때 비교가
된다 — 조합을 새로 뽑을 때마다 글까지 바뀌면 서체가 달라 보이는 건지 문장이
달라진 건지 알 수 없다. 사용자는 화면에서 직접 고쳐 쓸 수 있다.

영문 문구가 따로 있는 이유
------------------------
영문 전용 폰트에 한글 문구를 얹으면 글리프가 없어 통째로 깨진다. 지금 생성기가
영문 폰트를 영문 테마로 강제하는 것도(pairings.py의 _ENGLISH_THEMES) 같은 이유다.
카테고리마다 영문 한 벌을 두면 그 제약 없이 어느 카테고리에서든 영문을 쓸 수 있다.
"""

# (key, 화면 라벨, 묶는 기존 theme 목록)
# themes가 빈 것은 테마 필터를 쓰지 않는다는 뜻이다(뜻밖의 발견).
PAIR_CATEGORIES = [
    {
        "key": "video",
        "label": "영상 · 자막",
        "themes": ["유튜브 썸네일", "브이로그 자막", "인스타 릴스 · 숏폼 자막"],
        "ko": (
            "첫 3초가 전부입니다",
            "스크롤을 멈추게 하는 자막의 조건",
            "화면에서 읽는 글자는 종이와 다릅니다. 시청자는 한 문장을 붙잡고 있을 "
            "시간이 없어서, 자막은 흘끗 보는 동안 형태가 잡혀야 합니다. 획이 굵고 "
            "속이 트인 서체가 작은 화면에서 끝까지 버팁니다.",
        ),
        "en": (
            "Three Seconds to Hook",
            "What makes a caption stop the scroll",
            "Reading on screen is nothing like reading on paper. Viewers never linger "
            "on a sentence, so a caption has to resolve at a glance. Open counters and "
            "generous weight are what survive a small, moving frame.",
        ),
    },
    {
        "key": "sns",
        "label": "SNS · 카드뉴스",
        "themes": ["카드뉴스 · SNS", "이벤트 · 프로모션 배너"],
        "ko": (
            "한 장에 하나만 담기",
            "넘기게 만드는 카드의 리듬",
            "카드뉴스는 손가락이 결정합니다. 한 장에 문장을 욱여넣으면 넘기기 전에 "
            "지치고, 너무 비우면 다음 장을 눌러야 할 이유가 사라집니다. 제목은 크게 "
            "끊고 본문은 두 줄 안에서 끝내는 편이 잘 넘어갑니다.",
        ),
        "en": (
            "One Idea Per Card",
            "The rhythm that keeps a thumb moving",
            "A card deck is decided by the thumb. Cram a slide and the reader gives up "
            "before swiping; empty it and there is no reason to swipe at all. Break the "
            "headline large, keep the body inside two lines, and the deck carries itself.",
        ),
    },
    {
        "key": "brand",
        "label": "브랜딩 · 로고",
        "themes": [
            "명함 · 브랜드 로고", "감성 카페 · 브랜딩", "모던 미니멀 제목",
            "포인트 서체 조합", "영문 로고 · 캐치프레이즈",
        ],
        "ko": (
            "이름이 먼저 기억됩니다",
            "오래 쓸 서체를 고르는 기준",
            "브랜드의 서체는 유행보다 오래 남아야 합니다. 지금 새로워 보이는 형태일수록 "
            "몇 해 뒤에 그 시기를 드러냅니다. 획의 대비가 과하지 않고 자간이 고른 서체가, "
            "명함부터 간판까지 크기를 바꿔가며 견딥니다.",
        ),
        "en": (
            "The Name Is Remembered First",
            "Choosing a typeface you will keep for years",
            "A brand's typeface has to outlive the season it was chosen in. The shapes "
            "that look newest today are the ones that will date fastest. Moderate contrast "
            "and even spacing hold up from a business card to a storefront.",
        ),
    },
    {
        "key": "poster",
        "label": "포스터 · 안내",
        "themes": [
            "포스터 · 안내문", "시니어 친화 · 관공서", "큰 안내 본문",
            "굵은 산세리프 슬로건",
        ],
        "ko": (
            "멀리서도 읽히도록",
            "걸음을 멈추지 않아도 전달되는 글자",
            "안내문은 읽으려고 다가서는 글이 아닙니다. 지나가면서, 대개는 비스듬히, "
            "한 번에 봅니다. 그래서 굵기보다 글자통의 크기가 중요하고, 줄 사이가 좁으면 "
            "멀리서 한 덩어리로 뭉쳐 보입니다.",
        ),
        "en": (
            "Legible From Across the Room",
            "Words that land without slowing anyone down",
            "Signage is not read by someone leaning in. It is caught in passing, usually "
            "at an angle, in a single look. Character width matters more than weight, and "
            "lines set too tight collapse into one grey block at distance.",
        ),
    },
    {
        "key": "hand",
        "label": "감성 · 손글씨",
        "themes": ["캘리 · 손글씨 감성", "웨딩 · 청첩장", "키즈 · 교육 콘텐츠", "반려동물"],
        "ko": (
            "손으로 쓴 것처럼",
            "마음이 먼저 닿는 글씨",
            "어떤 문장은 내용보다 필적이 먼저 도착합니다. 청첩장이나 감사 카드처럼 한 번 "
            "읽고 오래 간직하는 글에서는, 반듯한 서체보다 조금 기울고 흔들리는 획이 더 "
            "오래 남습니다. 다만 길어지면 읽는 데 힘이 듭니다.",
        ),
        "en": (
            "As If Written by Hand",
            "Letters that arrive before the words do",
            "Some sentences land as handwriting before they land as meaning. On an "
            "invitation or a thank-you note, read once and kept for years, a stroke that "
            "leans and wavers outlasts a tidy one. Keep it short; it tires the eye.",
        ),
    },
    {
        "key": "read",
        "label": "본문 · 읽기",
        "themes": ["블로그 · 매거진 본문", "영문 본문 · 에디토리얼", "한글 + 영문 조합"],
        "ko": (
            "오래 읽어도 지치지 않게",
            "본문 서체가 하는 일은 사라지는 것",
            "좋은 본문 서체는 눈에 띄지 않습니다. 독자가 서체를 알아차렸다면 대개 무언가 "
            "불편했다는 뜻입니다. 글자 크기보다 줄 사이와 한 줄의 길이가 피로를 좌우하고, "
            "획의 굵기가 고를수록 문단이 고르게 회색으로 앉습니다.",
        ),
        "en": (
            "Built for the Long Read",
            "The body face does its job by disappearing",
            "A good text face goes unnoticed. If a reader has noticed the type, something "
            "was usually getting in the way. Line spacing and measure decide fatigue more "
            "than size does, and even stroke weight lets a paragraph settle into an even grey.",
        ),
    },
    {
        # 어울림 계산을 끄고 무작위로 뽑는 자리. themes가 비어 있어 테마 필터가 없다.
        "key": "surprise",
        "label": "뜻밖의 발견",
        "themes": [],
        "ko": (
            "계산에 없던 짝",
            "어울림은 자주 규칙 밖에 있습니다",
            "점수로 고르면 안전한 조합이 나옵니다. 그리고 안전한 것은 대체로 심심합니다. "
            "여기서는 어울림 계산을 끄고 무작위로 셋을 붙여 봅니다. 대부분은 어긋나지만, "
            "가끔 규칙으로는 절대 만나지 않았을 짝이 나옵니다.",
        ),
        "en": (
            "A Pair Nobody Calculated",
            "Good matches often sit outside the rules",
            "Scoring picks safe combinations, and safe is usually dull. Here the matching "
            "is switched off and three faces are thrown together at random. Most will "
            "clash. Once in a while you get a pair the rules would never have introduced.",
        ),
    },
]

DEFAULT_CATEGORY = "brand"
SURPRISE_CATEGORY = "surprise"

_BY_KEY = {c["key"]: c for c in PAIR_CATEGORIES}


def get_category(key: str) -> dict:
    """키로 카테고리를 찾는다. 모르는 키면 기본값으로 떨어진다 —
    주소를 손으로 고쳐 들어오는 경우가 있으므로 예외를 던지지 않는다."""
    return _BY_KEY.get(key or "") or _BY_KEY[DEFAULT_CATEGORY]


def themes_of(key: str) -> list:
    """그 카테고리가 묶는 기존 theme 목록. 빈 목록이면 '테마를 가리지 않는다'는 뜻."""
    return list(get_category(key)["themes"])


def specimen(key: str, script: str = "ko") -> dict:
    """견본 문구 세 줄. script는 'ko' | 'en' | 'mix'.

    mix는 제목만 영문으로 두고 나머지를 한글로 둔다 — 한글 화면에 영문 제목을
    얹는 것이 실제로 가장 흔한 혼용 방식이라, 그 배치를 그대로 보여준다.
    """
    c = get_category(key)
    ko, en = c["ko"], c["en"]
    if script == "en":
        t, s, b = en
    elif script == "mix":
        t, s, b = en[0], ko[1], ko[2]
    else:
        t, s, b = ko
    return {"title": t, "subtitle": s, "body": b}
