"""매거진 글에 붙일 설명 그림을 만든다 (static/mz/*.webp).

지어낸 그림이 아니라 **서비스하는 폰트 파일을 실제로 렌더링한 것**이다.
글자 수 그림은 정말로 그 글자가 없는 폰트로 그려서 빈칸이 나오고,
용량 그림은 파일을 실제로 변환·서브셋해 잰 값이다.

빌드 때 한 번 돌려 결과물을 저장소에 넣는다. 런타임에 만들지 않는 이유는
og_image.py 주석에 적힌 그대로다 — CJK 폰트를 여러 개 파싱하면 메모리가
순간적으로 크게 튄다. 그림은 몇 장 안 되고 자주 바뀌지도 않는다.

    python tools/make_mz_images.py

폰트를 바꾸거나 문구를 고치면 다시 돌리고 결과물을 함께 커밋한다.
"""
import io
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
OUT = ROOT / "static" / "mz"

# 그림 오른쪽 아래에 찍는 출처 표기. app/site.py 와 같은 환경변수를 본다 —
# 도메인을 옮기면 SITE_URL 을 주고 다시 돌려야 그림 속 주소도 따라간다.
MARK_HOST = os.getenv(
    "SITE_URL", "https://freefontpick.co.kr").rstrip("/").split("://", 1)[-1]

# 화면용 그림이라 2배로 그리고 줄인다 — 도형 가장자리가 훨씬 깨끗하다.
S = 2
W, H = 1200, 630

BG = (250, 250, 247)
CARD = (255, 255, 255)
LINE = (225, 225, 220)
LINE2 = (238, 238, 234)
T1 = (26, 26, 26)
T2 = (107, 107, 107)
T3 = (154, 154, 154)
ACC = (30, 58, 138)
ACCL = (238, 242, 251)
WARN = (176, 58, 46)
WARNL = (253, 240, 238)

# 라벨·설명에 쓰는 UI 폰트 (프리텐다드)
UI = 101

_cache = {}


def font(fid: int, size: int) -> ImageFont.FreeTypeFont:
    key = (fid, size)
    if key not in _cache:
        p = FONTS / ("font-%03d.woff2" % fid)
        if not p.exists():
            raise SystemExit("폰트 파일이 없다: %s" % p)
        _cache[key] = ImageFont.truetype(str(p), size * S)
    return _cache[key]


def has(fid: int, ch: str) -> bool:
    """그 폰트가 이 글자를 담고 있나. 대체 렌더링을 흉내 낼 때 쓴다."""
    from fontTools.ttLib import TTFont
    k = ("cmap", fid)
    if k not in _cache:
        _cache[k] = set(TTFont(str(FONTS / ("font-%03d.woff2" % fid))).getBestCmap())
    return ord(ch) in _cache[k]


class C:
    """논리 좌표(1200x630)로 그리면 알아서 2배로 그린다."""

    def __init__(self):
        self.im = Image.new("RGB", (W * S, H * S), BG)
        self.d = ImageDraw.Draw(self.im)

    def box(self, x, y, w, h, fill=CARD, outline=LINE, r=14, width=1):
        self.d.rounded_rectangle(
            [x * S, y * S, (x + w) * S, (y + h) * S], radius=r * S,
            fill=fill, outline=outline, width=max(1, width * S))

    def line(self, x1, y1, x2, y2, fill=LINE2, width=1):
        self.d.line([x1 * S, y1 * S, x2 * S, y2 * S], fill=fill, width=max(1, width * S))

    def t(self, x, y, s, fid=UI, size=16, fill=T1, anchor="la"):
        self.d.text((x * S, y * S), s, font=font(fid, size), fill=fill, anchor=anchor)

    def w_of(self, s, fid, size):
        b = self.d.textbbox((0, 0), s, font=font(fid, size))
        return (b[2] - b[0]) / S

    def adv(self, s, fid, size):
        """실제로 차지하는 폭. 없는 글자·공백은 잉크가 없어 w_of 가 0이 나오므로
        자리를 이어 그릴 때는 이쪽을 써야 한다."""
        return font(fid, size).getlength(s) / S

    def dashed(self, x, y, w, h, fill=(200, 200, 195), dash=7, gap=5):
        """'여기에 글자가 있어야 한다'고 우리가 표시하는 점선 자리."""
        pts = [((x, y), (x + w, y)), ((x, y + h), (x + w, y + h)),
               ((x, y), (x, y + h)), ((x + w, y), (x + w, y + h))]
        for (ax, ay), (bx, by) in pts:
            length = abs(bx - ax) + abs(by - ay)
            if length <= 0:
                continue
            ux, uy = (bx - ax) / length, (by - ay) / length
            t = 0.0
            while t < length:
                e = min(t + dash, length)
                self.d.line([(ax + ux * t) * S, (ay + uy * t) * S,
                             (ax + ux * e) * S, (ay + uy * e) * S],
                            fill=fill, width=max(1, int(1.5 * S)))
                t = e + gap

    def fit(self, s, fid, size, maxw):
        """maxw 안에 들어올 때까지 크기를 줄인다."""
        while size > 8 and self.w_of(s, fid, size) > maxw:
            size -= 1
        return size

    def mixed(self, x, y, s, main, fallback, size, fill=T1):
        """main 폰트에 없는 글자만 fallback 으로 그린다 — 브라우저가 하는 일 그대로."""
        cx = x
        for ch in s:
            fid = main if (ch == " " or has(main, ch)) else fallback
            self.d.text((cx * S, y * S), ch, font=font(fid, size), fill=fill, anchor="la")
            cx += self.adv(ch, fid, size)
        return cx - x

    def head(self, title, sub=None):
        self.t(64, 52, title, size=30, fill=T1)
        if sub:
            self.t(64, 96, sub, size=17, fill=T2)

    def mark(self):
        self.t(W - 64, H - 44, MARK_HOST, size=14, fill=T3, anchor="ra")

    def save(self, name):
        OUT.mkdir(parents=True, exist_ok=True)
        img = self.im.resize((W, H), Image.LANCZOS)
        p = OUT / name
        img.save(p, "WEBP", quality=86, method=6)
        print("  %-22s %6.1f KB" % (name, p.stat().st_size / 1024))


def tick(c, x, y, ok=True, size=22):
    """체크/엑스 표시를 도형으로 그린다 — 글리프에 기대지 않는다."""
    col = ACC if ok else WARN
    bg = ACCL if ok else WARNL
    r = size / 2
    c.d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=bg)
    if ok:
        c.d.line([(x - r * .45) * S, y * S, (x - r * .1) * S, (y + r * .38) * S],
                 fill=col, width=3 * S)
        c.d.line([(x - r * .1) * S, (y + r * .38) * S, (x + r * .48) * S, (y - r * .4) * S],
                 fill=col, width=3 * S)
    else:
        for a, b in (((-1, -1), (1, 1)), ((-1, 1), (1, -1))):
            c.d.line([(x + a[0] * r * .42) * S, (y + a[1] * r * .42) * S,
                      (x + b[0] * r * .42) * S, (y + b[1] * r * .42) * S],
                     fill=col, width=3 * S)


# ─────────────────────────────────────────────────────────────────
# 1. 같은 문장, 서체만 바꿨을 때
# ─────────────────────────────────────────────────────────────────
def img_font_guide():
    c = C()
    c.head("같은 문장, 서체만 바꿨습니다",
           "내용은 그대로인데 말투가 달라집니다. 폰트를 고른다는 건 이 말투를 고르는 일입니다.")
    rows = [
        (22, "나눔명조", "명조 — 차분하고 진중합니다"),
        (21, "나눔고딕", "고딕 — 튀지 않고 잘 읽힙니다"),
        (42, "배달의민족 주아체", "손글씨에서 나온 개성체 — 친근합니다"),
        (17, "검은고딕", "초굵은 제목용 — 멀리서도 보입니다"),
    ]
    y = 152
    sent = "새로 문을 연 동네 빵집"
    for i, (fid, name, note) in enumerate(rows):
        if i:
            c.line(64, y - 18, W - 64, y - 18)
        size = c.fit(sent, fid, 46, 600)
        c.t(64, y + (46 - size) / 2, sent, fid=fid, size=size, fill=T1)
        c.t(720, y + 8, name, size=17, fill=T1)
        c.t(720, y + 34, note, size=15, fill=T2)
        y += 112
    c.mark()
    c.save("same-sentence.webp")


# ─────────────────────────────────────────────────────────────────
# 2. 쓰는 자리마다 필요한 성질이 다르다
# ─────────────────────────────────────────────────────────────────
def img_by_purpose():
    c = C()
    c.head("쓰는 자리부터 정하면 고르기가 쉬워집니다",
           "자리마다 폰트에 요구하는 성질이 다릅니다.")
    cards = [
        ("썸네일 · 포스터", 17, 50, ["여름 정기", "세일 50%"],
         "멀리서도 읽히게. 굵고 큰 것."),
        ("본문 · 긴 글", 7, 19,
         ["오래 읽어도 눈이 덜 피로한", "글자가 필요합니다. 획이 고르고",
          "속공간이 넉넉한 본문용 폰트를", "고르면 읽는 속도가 달라집니다."],
         "개성보다 읽기 편한 것."),
        ("카드뉴스 · 감성", 52, 38, ["오늘도", "수고했어요"],
         "말투가 느껴지는 손글씨."),
    ]
    x, cw, gap, cy, ch = 64, 341, 24, 148, 366
    for label, fid, size, lines, note in cards:
        c.box(x, cy, cw, ch)
        c.box(x + 22, cy + 24, c.w_of(label, UI, 14) + 22, 26, fill=ACCL, outline=ACCL, r=13)
        c.t(x + 33, cy + 30, label, size=14, fill=ACC)
        ly = cy + 84
        for ln in lines:
            s2 = c.fit(ln, fid, size, cw - 48)
            c.t(x + 24, ly, ln, fid=fid, size=s2, fill=T1)
            ly += size + (12 if size > 30 else 8)
        c.line(x + 24, cy + ch - 62, x + cw - 24, cy + ch - 62)
        c.t(x + 24, cy + ch - 44, note, size=15, fill=T2)
        x += cw + gap
    c.mark()
    c.save("by-purpose.webp")


# ─────────────────────────────────────────────────────────────────
# 3. 제목과 본문 짝짓기
# ─────────────────────────────────────────────────────────────────
def img_pairing():
    c = C()
    c.head("제목과 본문은 맡은 역할이 다릅니다",
           "폰트가 나쁜 게 아니라 짝이 안 맞는 것입니다.")
    body = ["여름을 맞아 전 품목을 정리합니다.", "재고가 있는 동안만 진행하며,",
            "매장과 온라인에서 함께 적용됩니다."]
    panels = [
        (64, True, "잘 맞는 짝", 17, 21,
         "제목만 개성을 주고 본문은 조용하게 뒀습니다."),
        (616, False, "부딪히는 짝", 90, 52,
         "둘 다 개성이 강해 서로 시선을 뺏습니다."),
    ]
    for x, ok, label, tfid, bfid, note in panels:
        c.box(x, 148, 520, 396)
        tick(c, x + 40, 186, ok)
        c.t(x + 64, 175, label, size=17, fill=(ACC if ok else WARN))
        title = "여름 정기 세일"
        ts = c.fit(title, tfid, 40, 440)
        c.t(x + 30, 236, title, fid=tfid, size=ts, fill=T1)
        by = 312
        for ln in body:
            bs = c.fit(ln, bfid, 17, 460)
            c.t(x + 30, by, ln, fid=bfid, size=bs, fill=T2)
            by += 32
        c.line(x + 30, 462, x + 490, 462)
        c.t(x + 30, 480, note, size=15, fill=T2)
    c.mark()
    c.save("pairing.webp")


# ─────────────────────────────────────────────────────────────────
# 4. 라이선스에서 확인할 여섯 자리
# ─────────────────────────────────────────────────────────────────
def img_license():
    c = C()
    c.head("무료여도 자리마다 허용 범위가 다릅니다",
           "‘무료’는 한 덩어리가 아닙니다. 아래 여섯 자리를 따로따로 확인해야 합니다.")
    cells = [
        ("인쇄물", "포스터 · 명함 · 책", "대개 열려 있는 자리"),
        ("웹사이트", "이미지 · 웹폰트", "이미지는 되고 웹폰트는 막는 경우"),
        ("포장지 · 굿즈", "판매하는 물건에", "파는 물건이면 따로 묻는 경우"),
        ("영상 · 자막", "유튜브 · 광고", "영상만 통째로 막아 둔 폰트도"),
        ("앱 임베딩", "폰트 파일을 앱에 넣기", "재배포로 보는 경우"),
        ("BI · CI 로고", "상표 등록까지", "가장 자주 막히는 자리"),
    ]
    x0, y0, cw, ch, gx, gy = 64, 152, 341, 138, 24, 20
    for i, (name, sub, note) in enumerate(cells):
        x = x0 + (i % 3) * (cw + gx)
        y = y0 + (i // 3) * (ch + gy)
        c.box(x, y, cw, ch)
        c.box(x + 22, y + 24, 30, 30, fill=ACCL, outline=ACCL, r=9)
        c.t(x + 37, y + 39, str(i + 1), size=16, fill=ACC, anchor="mm")
        c.t(x + 64, y + 26, name, size=18, fill=T1)
        c.t(x + 64, y + 53, sub, size=14, fill=T2)
        c.line(x + 22, y + 90, x + cw - 22, y + 90)
        c.t(x + 22, y + 104, note, size=14, fill=T3)
    c.line(64, 476, W - 64, 476)
    c.t(64, 496, "여섯 자리를 한꺼번에 '무료'로 묶어 두는 폰트는 드뭅니다. "
                 "폰트픽은 폰트마다 이 항목을 하나씩 표시합니다.", size=15, fill=T2)
    c.mark()
    c.save("license-six.webp")


# ─────────────────────────────────────────────────────────────────
# 5. 폰트에 없는 글자 — 실제로 없는 폰트로 그린다
# ─────────────────────────────────────────────────────────────────
FULL, SMALL, LATIN, FB = 7, 49, 135, 21   # KoPub돋움 / 빛의계승자체 / Montserrat / 나눔고딕


def img_glyphs():
    c = C()
    c.head("폰트에 없는 글자는 그냥 사라집니다",
           "네모로 바뀌는 게 아니라, 그 자리가 비거나 다른 서체로 대체됩니다.")
    sample = "뷁 뷃 묷 믜 븨 싀"
    for x, fid, label, sub in (
        (64, FULL, "11,172자를 담은 폰트", "KoPub돋움 — 여섯 자 모두 나옵니다"),
        (616, SMALL, "2,350자만 담은 폰트", "빛의계승자체 — 여섯 자 모두 없습니다"),
    ):
        c.box(x, 148, 520, 208)
        c.t(x + 30, 172, label, size=16, fill=T1)
        size = 46
        cx = x + 30
        for ch in sample:
            w = c.adv(ch, fid, size)
            if ch == " " or has(fid, ch):
                c.t(cx, 222, ch, fid=fid, size=size, fill=T1)
            else:
                # 실제 화면에는 아무것도 안 나온다. 자리를 우리가 점선으로 표시한다.
                c.dashed(cx + 3, 226, w - 6, size * 1.06)
            cx += w
        c.t(x + 30, 312, sub, size=14, fill=T2)
    c.t(616 + 30 + 300, 176, "점선 = 폰트픽이 표시한 빈자리", size=13, fill=T3)

    c.box(64, 384, W - 128, 168, fill=CARD)
    c.t(94, 408, "웹에서는 그 빈자리에 다른 폰트가 대신 들어옵니다",
        size=16, fill=T1)
    c.mixed(94, 444, "안녕하세요 Montserrat", LATIN, FB, 40)
    c.t(94, 506,
        "영문 전용 폰트(Montserrat)로 지정한 줄입니다. 한글이 그 폰트에 없어서 "
        "그 부분만 서체가 바뀌었습니다 — 깨진 것처럼 보이지 않아 놓치기 쉽습니다.",
        size=14, fill=T2)
    c.mark()
    c.save("missing-glyphs.webp")


# ─────────────────────────────────────────────────────────────────
# 6. 웹폰트 용량 — 실제로 변환해서 잰다
# ─────────────────────────────────────────────────────────────────
def measure_sizes(fid: int):
    """원본 sfnt / woff2 / 2,350자 서브셋 woff2 크기를 실제로 만들어 잰다."""
    from fontTools.ttLib import TTFont
    from fontTools.subset import Subsetter

    src = FONTS / ("font-%03d.woff2" % fid)
    woff2 = src.stat().st_size

    f = TTFont(str(src))
    f.flavor = None                      # woff2 압축을 풀어 원래 ttf 로
    b = io.BytesIO()
    f.save(b)
    raw = len(b.getvalue())

    # KS 완성형 2,350자에 해당하는 만큼만 남긴다 (여기서는 폰트가 가진 것 중
    # 앞에서부터 2,350자 — 정확한 KS 목록이 없어도 '줄었을 때 얼마인가'는 같다)
    f2 = TTFont(str(src))
    cm = sorted(c for c in f2.getBestCmap() if 0xAC00 <= c <= 0xD7A3)[:2350]
    keep = cm + [c for c in f2.getBestCmap() if c < 0xAC00]
    ss = Subsetter()
    ss.populate(unicodes=keep)
    ss.subset(f2)
    f2.flavor = "woff2"
    b2 = io.BytesIO()
    f2.save(b2)
    return raw, woff2, len(b2.getvalue())


def img_webfont():
    c = C()
    fid = FULL
    raw, w2, sub = measure_sizes(fid)
    c.head("웹폰트는 같은 글자를 훨씬 가볍게 실어 나릅니다",
           "폰트픽이 서비스하는 KoPub돋움 파일을 직접 변환해 잰 값입니다.")
    bars = [
        ("압축 안 한 TTF", raw, (168, 168, 160)),
        ("WOFF2", w2, ACC),
        ("WOFF2 + 2,350자만", sub, (90, 130, 224)),
    ]
    top = max(b[1] for b in bars)
    x0, y0, bw, maxw = 300, 190, 46, 760
    for i, (label, size, col) in enumerate(bars):
        y = y0 + i * 104
        wpx = max(8, maxw * size / top)
        c.t(x0 - 24, y + bw / 2, label, size=17, fill=T1, anchor="rm")
        c.d.rounded_rectangle([x0 * S, y * S, (x0 + wpx) * S, (y + bw) * S],
                              radius=8 * S, fill=col)
        c.t(x0 + wpx + 16, y + bw / 2, "%.0f KB" % (size / 1024),
            size=17, fill=T1, anchor="lm")
    c.line(64, 520, W - 64, 520)
    c.t(64, 542,
        "글자를 덜어내면 더 줄지만, 덜어낸 글자는 화면에서 사라집니다. "
        "이름·주소가 들어가는 자리라면 함부로 줄이면 안 됩니다.", size=15, fill=T2)
    c.mark()
    c.save("webfont-size.webp")
    return raw, w2, sub


# ────────────────────────────────────────
# 7. 굵기는 번호가 아니라 실물로 봐야 한다
# ────────────────────────────────────────
def wfont(rel: str, size: int):
    """굵기 파일을 경로로 직접 연다. fonts/weights/ 아래에 있다."""
    key = (rel, size)
    if key not in _cache:
        p = FONTS / rel if (FONTS / rel).exists() else FONTS / "weights" / rel
        if not p.exists():
            raise SystemExit("폰트 파일이 없다: %s" % p)
        _cache[key] = ImageFont.truetype(str(p), size * S)
    return _cache[key]


def img_weight():
    """선언된 굵기와 실제 두께가 따로 논다는 것을 한 화면에 보인다.

    네 폰트 모두 저장소에 있는 실제 파일로 그린다. 채움비율은 글에 실린
    실측값이다(가나다라마바사아자차카타파하 14자의 잉크 면적 ÷ 상자 넓이).
    """
    c = C()
    c.head("굵기 번호는 약속이 아닙니다",
           "같은 글자를 실제 폰트 파일로 그렸습니다. 아래 숫자가 잰 두께입니다.")

    cols = [
        ("aritaburi-100.woff2", "아리따 부리", "100", "0.059"),
        ("../font-093.woff2",   "카페24 아네모네", "400", "0.570"),
        ("cookierun-900.woff2", "쿠키런",     "900", "0.682"),
        ("../font-075.woff2",   "이누아리두리네", "900", "0.820"),
    ]
    x, gap, w = 64, 16, 258
    for rel, name, declared, ratio in cols:
        c.box(x, 152, w, 392)
        # 큰 글자 — 이 그림의 주인공
        c.d.text(((x + w // 2) * S, 300 * S), "가", font=wfont(rel, 132),
                 fill=T1, anchor="mm")
        c.line(x + 24, 392, x + w - 24, 392)
        c.t(x + w // 2, 410, name, size=16, fill=T1, anchor="ma")
        c.t(x + w // 2, 440, "선언 " + declared, size=14, fill=T3, anchor="ma")
        c.t(x + w // 2, 476, ratio, size=32, fill=ACC, anchor="ma")
        c.t(x + w // 2, 516, "채움비율", size=13, fill=T2, anchor="ma")
        x += w + gap

    c.t(64, 570, "선언 400 이 900 에 가깝고, 100 과는 10 배 가까이 벌어집니다. "
                 "번호만 보고 짝을 맞추면 위계가 뒤집힙니다.", size=15, fill=T2)
    c.mark()
    c.save("weight-scale.webp")


def main():
    print("매거진 그림을 만든다 →", OUT)
    img_font_guide()
    img_by_purpose()
    img_pairing()
    img_license()
    img_glyphs()
    img_weight()
    r = img_webfont()
    print("\n웹폰트 실측: 원본 %.0fKB / woff2 %.0fKB / 서브셋 %.0fKB"
          % (r[0] / 1024, r[1] / 1024, r[2] / 1024))


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
