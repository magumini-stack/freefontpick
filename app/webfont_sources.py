"""공식 웹폰트 주소 — 상세페이지 오른쪽 '웹폰트로 쓰기' 칸 (2026-10-06).

사용자님 제안: "웹폰트로 많이 쓰이는 폰트는 웹폰트 URL 을 주면 좋겠다. 우리 서버에서 내주면
감당이 안 되니, 원래 제공하는 곳이 있으면 찾아서 소스만 알려 주자." 정하신 것: 눈누는 빼고,
전체를 조사해서 넣고, 자리는 오른쪽 '같은 계열 폰트' 위.

넣는 기준
  · 공식 배포처만 — 구글 폰트, 네이버, 제작사 CDN, 제작자가 직접 안내하는 저장소(jsDelivr·GitHub).
    눈누(projectnoonnu)를 비롯한 남이 올린 사본·미러는 넣지 않는다.
  · 제작사가 자기 홈페이지를 꾸미려고 부르는 CSS 는 넣지 않는다(G마켓 산스·쿠키런·배달의민족·
    런드리고딕 등). 공개한 주소가 아니라 남의 대역폭이고, 사이트를 고치면 예고 없이 사라진다.
    페이지 본문에 코드로 적어 안내하는 경우만 공식으로 본다(양진체·던파 연단된 칼날).
  · 폰트픽 서버에서는 아무것도 내주지 않는다. 화면은 주소와 출처만 보여 준다.

보여 줄지는 화면이 정한다(app/routers/design.py _webfont_block): 라이선스를 확인했고 '임베딩'이
가능(y)이나 조건부(c)일 때만. 그래서 여기 있어도 라이선스가 미확인·불가면 안 보인다
(던파 연단된 칼날은 지금 '확인 필요'라 숨어 있다).

검증(2026-10-06, 115종 전부 통과): CSS 를 받아 @font-face 가 오는지, 안내할 font-family 이름이
그 안에 있는지, 글꼴 파일을 다른 사이트에서 부른 것처럼 받아 200·CORS 허용인지.
조사한 527종 중 이 표에 없는 폰트는 공식 웹폰트 주소를 찾지 못한 것이다
(카페24·넥슨·가비아·조선일보·학교안심·온글잎 등은 파일 내려받기만 있다).

칸
  css              <link> 로 부를 CSS 주소           fontface  CSS 파일 없이 안내하는 @font-face 코드
  family           font-family 에 쓸 이름            generic   이름 뒤에 붙일 기본 서체(sans-serif·serif·monospace)
  weights_by_name  굵기마다 따로 붙은 이름(네이버)   note      한 줄 덧붙임
  provider         내주는 곳(화면에 그대로)          src       그곳의 안내 페이지(origin 이 있으면 그 저장소)
  origin           jsDelivr 로 받는 것의 원본 — 제작자의 공식 저장소(owner/repo)
"""

NAVER = "네이버 한글한글 아름답게"
# jsDelivr 는 제작자가 GitHub·npm 에 올린 파일을 그대로 전해 주는 무료 CDN 이다. 폰트를 만든 것도,
# 파일을 올린 것도 제작자다. 그래서 '제공'은 jsDelivr, '원본'(origin)은 제작자의 공식 저장소로 나눠 적는다.
# (처음엔 'jsDelivr · 제작자 GitHub'이라고 한 줄로 썼는데 '제작자가 GitHub'으로 읽힌다는
#  사용자님 지적을 받고 나눴다, 2026-10-06)
JSD = "jsDelivr 무료 CDN"


def _gf(family: str, axis: str = "", generic: str = "sans-serif") -> dict:
    q = family.replace(" ", "+") + (":" + axis if axis else "")
    return {
        "css": f"https://fonts.googleapis.com/css2?family={q}&display=swap",
        "family": family,
        "generic": generic,
        "provider": "Google Fonts",
        "src": "https://fonts.google.com/specimen/" + family.replace(" ", "+"),
    }


WEBFONT_SOURCES = {
    # ── 구글 폰트 — fonts.google.com 의 css2 주소. 가변폰트는 굵기 범위(wght@100..900)로 부른다. (90종)
    10: _gf("Noto Sans KR", "wght@100..900"),  # Noto Sans CJK KR
    17: _gf("Black Han Sans"),  # 검은고딕
    21: _gf("Nanum Gothic", "wght@400;700;800"),  # 나눔고딕
    22: _gf("Nanum Myeongjo", "wght@400;700;800", generic="serif"),  # 나눔명조
    42: _gf("Jua"),  # 배달의민족 주아체
    44: _gf("Do Hyeon"),  # 배달의민족 도현체
    108: _gf("Anton"),  # Anton
    110: _gf("Bangers"),  # BANGERS
    112: _gf("Blaka"),  # Blaka
    113: _gf("Blaka Hollow"),  # BlakaHollow
    115: _gf("Bona Nova", "wght@400;700", generic="serif"),  # BonaNova
    116: _gf("Bungee"),  # Bungee
    120: _gf("Cinzel Decorative", "wght@400;700;900"),  # CinzelDecorative
    121: _gf("Dancing Script", "wght@400..700"),  # DancingScript
    125: _gf("Kaushan Script"),  # KaushanScript
    126: _gf("Kdam Thmor Pro"),  # KdamThmorPro
    128: _gf("Libre Bodoni", "wght@400..700", generic="serif"),  # LibreBodoni
    129: _gf("Lobster"),  # Lobster
    134: _gf("Monoton"),  # Monoton
    135: _gf("Montserrat", "wght@100..900"),  # Montserrat
    136: _gf("Open Sans", "wght@300..800"),  # OpenSans
    137: _gf("Pavanam"),  # Pavanam
    138: _gf("Petrona", "wght@100..900", generic="serif"),  # Petrona
    139: _gf("Playfair Display", "wght@400..900", generic="serif"),  # Playfair Display
    140: _gf("Press Start 2P"),  # PressStart2P
    141: _gf("Raleway", "wght@100..900"),  # Raleway
    142: _gf("Roboto", "wght@100..900"),  # Roboto
    156: _gf("Gowun Batang", "wght@400;700", generic="serif"),  # 고운바탕
    162: _gf("Gowun Dodum"),  # 고운돋움
    181: _gf("IBM Plex Sans KR", "wght@100;200;300;400;500;600;700"),  # IBM Plex Sans KR
    182: _gf("Hahmlet", "wght@100..900", generic="serif"),  # 함렛
    183: _gf("Bebas Neue"),  # Bebas Neue
    184: _gf("Diphylleia", generic="serif"),  # 산하엽
    198: _gf("Gaegu", "wght@300;400;700"),  # J개구쟁이
    199: _gf("Poor Story"),  # 푸어스토리
    201: _gf("Gothic A1", "wght@100;200;300;400;500;600;700;800;900"),  # A1 고딕
    202: _gf("East Sea Dokdo"),  # 대한민국 독도체
    203: _gf("Noto Serif KR", "wght@200..900", generic="serif"),  # Noto Serif KR
    227: _gf("Nanum Brush Script"),  # 나눔손글씨붓
    250: _gf("Yeon Sung"),  # 배달의민족 연성체
    253: _gf("Kirang Haerang"),  # 배달의민족 기랑해랑체
    269: _gf("Nanum Pen Script"),  # 나눔손글씨 펜
    305: _gf("Asta Sans", "wght@300..800"),  # 아스타 산스 (Asta Sans)
    318: _gf("Sunflower", "wght@300;500;700"),  # Sunflower
    324: _gf("Song Myung", generic="serif"),  # Song Myung (송명)
    327: _gf("Diphylleia", generic="serif"),  # Diphylleia (산하엽)
    331: _gf("Dongle", "wght@300;400;700"),  # Dongle (동글)
    332: _gf("Cute Font"),  # Cute Font
    333: _gf("Black And White Picture"),  # Black And White Picture
    386: _gf("Inter", "wght@100..900"),  # Inter
    387: _gf("Poppins", "wght@100;200;300;400;500;600;700;800;900"),  # Poppins
    388: _gf("DM Sans", "wght@100..1000"),  # DM Sans
    389: _gf("Oswald", "wght@200..700"),  # Oswald
    390: _gf("Lora", "wght@400..700", generic="serif"),  # Lora
    391: _gf("Fraunces", "wght@100..900", generic="serif"),  # Fraunces
    392: _gf("Instrument Serif", generic="serif"),  # Instrument Serif
    393: _gf("Cormorant Garamond", "wght@300..700", generic="serif"),  # Cormorant Garamond
    394: _gf("Caveat", "wght@400..700"),  # Caveat
    395: _gf("Pacifico"),  # Pacifico
    471: _gf("Lato", "wght@100;300;400;700;900"),  # Lato
    472: _gf("Nunito", "wght@200..1000"),  # Nunito
    473: _gf("Rubik", "wght@300..900"),  # Rubik
    474: _gf("Manrope", "wght@200..800"),  # Manrope
    475: _gf("Outfit", "wght@100..900"),  # Outfit
    476: _gf("Work Sans", "wght@100..900"),  # Work Sans
    477: _gf("Plus Jakarta Sans", "wght@200..800"),  # Plus Jakarta Sans
    478: _gf("Figtree", "wght@300..900"),  # Figtree
    479: _gf("Space Grotesk", "wght@300..700"),  # Space Grotesk
    480: _gf("Bricolage Grotesque", "wght@200..800"),  # Bricolage Grotesque
    481: _gf("Jost", "wght@100..900"),  # Jost
    482: _gf("Quicksand", "wght@300..700"),  # Quicksand
    483: _gf("Merriweather", "wght@300..900", generic="serif"),  # Merriweather
    484: _gf("Libre Baskerville", "wght@400..700", generic="serif"),  # Libre Baskerville
    485: _gf("EB Garamond", "wght@400..800", generic="serif"),  # EB Garamond
    486: _gf("DM Serif Display", generic="serif"),  # DM Serif Display
    487: _gf("Cinzel", "wght@400..900", generic="serif"),  # Cinzel
    488: _gf("Source Serif 4", "wght@200..900", generic="serif"),  # Source Serif 4
    489: _gf("Archivo Black"),  # Archivo Black
    490: _gf("Abril Fatface"),  # Abril Fatface
    491: _gf("Alfa Slab One"),  # Alfa Slab One
    492: _gf("Righteous"),  # Righteous
    493: _gf("Lilita One"),  # Lilita One
    494: _gf("Great Vibes"),  # Great Vibes
    495: _gf("Permanent Marker"),  # Permanent Marker
    496: _gf("Amatic SC", "wght@400;700"),  # Amatic SC
    497: _gf("Sacramento"),  # Sacramento
    498: _gf("Shadows Into Light"),  # Shadows Into Light
    499: _gf("JetBrains Mono", "wght@100..800", generic="monospace"),  # JetBrains Mono
    500: _gf("Space Mono", "wght@400;700", generic="monospace"),  # Space Mono
    527: _gf("Nanum Gothic Coding", "wght@400;700"),  # 나눔고딕코딩

    # ── 네이버 한글한글 아름답게 — hangeul.naver.com/font 의 '웹폰트 URL'. 굵기마다 font-family 이름이 따로다. (9종)
    23: {  # 나눔스퀘어
        "css": "https://hangeul.pstatic.net/hangeul_static/css/nanum-square.css",
        "family": "NanumSquare",
        "generic": "sans-serif",
        "weights_by_name": ["NanumSquareLight", "NanumSquareBold", "NanumSquareExtraBold"],
        "provider": NAVER,
        "src": "https://hangeul.naver.com/font",
    },
    33: {  # 마루부리
        "css": "https://hangeul.pstatic.net/hangeul_static/css/maru-buri.css",
        "family": "MaruBuri",
        "generic": "serif",
        "weights_by_name": ["MaruBuriExtraLight", "MaruBuriLight", "MaruBuriSemiBold", "MaruBuriBold"],
        "provider": NAVER,
        "src": "https://hangeul.naver.com/font",
    },
    263: {  # 나눔바른펜
        "css": "https://hangeul.pstatic.net/hangeul_static/css/nanum-barun-pen.css",
        "family": "NanumBarunpen",
        "generic": "sans-serif",
        "weights_by_name": ["NanumBarunpenB"],
        "provider": NAVER,
        "src": "https://hangeul.naver.com/font",
    },
    302: {  # 나눔바른고딕
        "css": "https://hangeul.pstatic.net/hangeul_static/css/nanum-barun-gothic.css",
        "family": "NanumBarunGothic",
        "generic": "sans-serif",
        "weights_by_name": ["NanumBareunGothicUltraLight", "NanumBareunGothicLight", "NanumBarunGothicBold"],
        "provider": NAVER,
        "src": "https://hangeul.naver.com/font",
    },
    303: {  # 나눔스퀘어라운드
        "css": "https://hangeul.pstatic.net/hangeul_static/css/nanum-square-round.css",
        "family": "NanumSquareRound",
        "generic": "sans-serif",
        "weights_by_name": ["NanumSquareRoundL", "NanumSquareRoundB", "NanumSquareRoundEB"],
        "provider": NAVER,
        "src": "https://hangeul.naver.com/font",
    },
    368: {  # D2Coding
        "css": "https://hangeul.pstatic.net/hangeul_static/css/nanum-gothic-coding.css",
        "family": "NanumGothicCoding",
        "generic": "monospace",
        "weights_by_name": ["NanumGothicCodingBold", "NanumGothicCodingLigature", "NanumGothicCodingLigatureBold"],
        "note": "네이버는 D2Coding 을 이 이름으로 내보내요.",
        "provider": NAVER,
        "src": "https://hangeul.naver.com/font",
    },
    398: {  # 나눔스퀘어 네오
        "css": "https://hangeul.pstatic.net/hangeul_static/css/nanum-square-neo.css",
        "family": "NanumSquareNeo",
        "generic": "sans-serif",
        "weights_by_name": ["NanumSquareNeoLight", "NanumSquareNeoBold", "NanumSquareNeoExtraBold", "NanumSquareNeoHeavy"],
        "provider": NAVER,
        "src": "https://hangeul.naver.com/font",
    },
    458: {  # 고딕 아니고 고딩
        "css": "https://hangeul.pstatic.net/hangeul_static/css/NanumGoDigANiGoGoDing.css",
        "family": "NanumGoDigANiGoGoDing",
        "generic": "sans-serif",
        "provider": NAVER,
        "src": "https://hangeul.naver.com/font",
    },
    523: {  # 나눔손글씨 바른히피
        "css": "https://hangeul.pstatic.net/hangeul_static/css/NanumBaReunHiPi.css",
        "family": "NanumBaReunHiPi",
        "generic": "sans-serif",
        "provider": NAVER,
        "src": "https://hangeul.naver.com/font",
    },

    # ── 제작사 CDN — 제작사가 자기 주소로 내주는 것 (5종)
    179: {  # 던파 연단된 칼날
        "fontface": (
            "@font-face {\n"
            "  font-family: 'DNFForgedBlade';\n"
            "  font-weight: 300;\n"
            "  src: url('https://cdn.df.nexon.com/img/common/font/DNFForgedBlade-Light.otf') format('opentype');\n"
            "}\n"
            "@font-face {\n"
            "  font-family: 'DNFForgedBlade';\n"
            "  font-weight: 500;\n"
            "  src: url('https://cdn.df.nexon.com/img/common/font/DNFForgedBlade-Medium.otf') format('opentype');\n"
            "}\n"
            "@font-face {\n"
            "  font-family: 'DNFForgedBlade';\n"
            "  font-weight: 700;\n"
            "  src: url('https://cdn.df.nexon.com/img/common/font/DNFForgedBlade-Bold.otf') format('opentype');\n"
            "}"
        ),
        "family": "DNFForgedBlade",
        "generic": "sans-serif",
        "note": "OTF 원본이라 굵기마다 4MB 가까이 돼요. 제목에만 쓰는 걸 권해요.",
        "provider": "넥슨 던전앤파이터",
        "src": "https://df.nexon.com/data/font",
    },
    193: {  # 구름산스
        "css": "https://statics.goorm.io/fonts/GoormSans/v1.0.0/GoormSans.min.css",
        "family": "Goorm Sans",
        "generic": "sans-serif",
        "provider": "구름(goorm)",
        "src": "https://goorm.co/resources/fonts",
    },
    233: {  # 엘리스 DX널리체
        "css": "https://font.elice.io/css?family=Elice+DX+Neolli",
        "family": "Elice DX Neolli",
        "generic": "sans-serif",
        "provider": "엘리스",
        "src": "https://font.elice.io/",
    },
    234: {  # 엘리스 디지털코딩체
        "css": "https://font.elice.io/css?family=Elice+Digital+Coding",
        "family": "Elice Digital Coding",
        "generic": "monospace",
        "provider": "엘리스",
        "src": "https://font.elice.io/",
    },
    235: {  # 엘리스 디지털배움체
        "css": "https://font.elice.io/css?family=Elice+Digital+Baeum",
        "family": "Elice Digital Baeum",
        "generic": "sans-serif",
        "provider": "엘리스",
        "src": "https://font.elice.io/",
    },

    # ── 제작자 저장소 — 제작자가 README·공식 페이지에서 안내하는 jsDelivr(GitHub·npm)·GitHub Pages 주소 (11종)
    56: {  # 스포카 한 산스
        "css": "https://spoqa.github.io/spoqa-han-sans/css/SpoqaHanSansNeo.css",
        "family": "Spoqa Han Sans Neo",
        "generic": "sans-serif",
        "provider": "스포카",
        "src": "https://spoqa.github.io/spoqa-han-sans/ko-KR/",
    },
    98: {  # 페이퍼로지
        "css": "https://cdn.jsdelivr.net/gh/Freesentation/paperlogy@main/Paperlogy.css",
        "family": "Paperlogy",
        "generic": "sans-serif",
        "provider": JSD,
        "origin": "Freesentation/paperlogy",
        "src": "https://github.com/Freesentation/paperlogy",
    },
    101: {  # 프리텐다드
        "css": "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css",
        "family": "Pretendard Variable",
        "generic": "sans-serif",
        "provider": JSD,
        "origin": "orioncactus/pretendard",
        "src": "https://github.com/orioncactus/pretendard",
    },
    157: {  # 수트
        "css": "https://cdn.jsdelivr.net/gh/sun-typeface/SUIT@2/fonts/variable/woff2/SUIT-Variable.css",
        "family": "SUIT Variable",
        "generic": "sans-serif",
        "provider": JSD,
        "origin": "sun-typeface/SUIT",
        "src": "https://github.com/sun-typeface/SUIT",
    },
    191: {  # 원티드산스
        "css": "https://cdn.jsdelivr.net/gh/wanteddev/wanted-sans@v1.0.3/packages/wanted-sans/fonts/webfonts/variable/split/WantedSansVariable.min.css",
        "family": "Wanted Sans Variable",
        "generic": "sans-serif",
        "provider": JSD,
        "origin": "wanteddev/wanted-sans",
        "src": "https://github.com/wanteddev/wanted-sans",
    },
    209: {  # 프리젠테이션
        "css": "https://cdn.jsdelivr.net/gh/Freesentation/freesentation@main/Freesentation.css",
        "family": "Freesentation",
        "generic": "sans-serif",
        "provider": JSD,
        "origin": "Freesentation/freesentation",
        "src": "https://github.com/Freesentation/freesentation",
    },
    213: {  # Mona12
        "css": "https://cdn.jsdelivr.net/gh/MonadABXY/mona-font/web/mona.css",
        "family": "Mona12",
        "generic": "monospace",
        "provider": JSD,
        "origin": "MonadABXY/mona-font",
        "src": "https://github.com/MonadABXY/mona-font",
    },
    214: {  # 갈무리14
        "css": "https://cdn.jsdelivr.net/npm/galmuri/dist/galmuri.css",
        "family": "Galmuri14",
        "generic": "sans-serif",
        "provider": JSD,
        "origin": "quiple/galmuri",
        "src": "https://github.com/quiple/galmuri",
    },
    366: {  # Neo둥근모
        "css": "https://cdn.jsdelivr.net/gh/neodgm/neodgm-webfont@1.601/neodgm/style.css",
        "family": "NeoDunggeunmo",
        "generic": "monospace",
        "provider": JSD,
        "origin": "neodgm/neodgm-webfont",
        "src": "https://github.com/neodgm/neodgm-webfont",
    },
    401: {  # 갈무리9
        "css": "https://cdn.jsdelivr.net/npm/galmuri/dist/galmuri.css",
        "family": "Galmuri9",
        "generic": "sans-serif",
        "provider": JSD,
        "origin": "quiple/galmuri",
        "src": "https://github.com/quiple/galmuri",
    },
    405: {  # 양진체
        "fontface": (
            "@font-face {\n"
            "  font-family: 'yangjin';\n"
            "  src: url('https://cdn.jsdelivr.net/gh/supernovice-lab/font@0.9/yangjin.woff') format('woff');\n"
            "  font-weight: normal;\n"
            "  font-style: normal;\n"
            "}"
        ),
        "family": "yangjin",
        "generic": "sans-serif",
        "provider": JSD,
        "origin": "supernovice-lab/font",
        "src": "https://github.com/supernovice-lab/font",
    },
}
