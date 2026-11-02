"""한글 디자인 요소 재기(2026-11-02 사용자님: "고딕인데 ㅎ의 꼭지가 서 있는 것과 누워 있는 것은 아예 구분을 안 한다").

사람은 폰트를 '전체 모양'보다 몇 가지 요소로 가른다. 지금 엔진(모양 48칸·새 눈 줄 높이 64px)은 글자를 작게 줄여 봐서
ㅎ 꼭지 같은 2~4px 짜리 요소를 못 본다 — 고딕 177종에서 엔진이 가장 닮았다고 본 10개 중 꼭지가 같은 것 69%
(아무거나 54%)인데, 사용자님 폰트끼리 판단에선 꼭지가 다른 후보 72개 중 99%가 '아님'이었다.
그래서 요소를 따로 재서 견준다.

  꼭지(ㅎ·ㅊ) : '서'(세로로 선 짧은 획) / '누'(가로로 누운 획). ㅎ 가로줄(ㅊ 은 ㅈ 윗줄) 위의 잉크 폭을 그 가로줄
               굵기와 견준다 — 획 굵기만 한 폭이면 선 것, 훨씬 넓으면 누운 것.
  ㅇ 모양      : 너비 ÷ 높이(정원 1.0 · 납작 > 1.15 · 홀쭉 < 0.9)
  기울기       : 'ㅣ' 세로획의 기울기(도, 오른쪽으로 누우면 +)

폰트 쪽(font_profile)은 깨끗하게 그린 글자로, 사진 쪽(line_kkokji)은 엔진이 떼어 낸 글자 마스크로 같은 규칙을 쓴다.
글자 짜임(세로 모음이면 초성이 왼쪽, 가로 모음이면 위)을 보고 초성 자리에서만 찾는다.
"""
import numpy as np

CHO_KK = {14: "ㅊ", 18: "ㅎ"}                      # 초성 번호 → 꼭지 있는 자음
JUNG_VERT = {0, 1, 2, 3, 4, 5, 6, 7, 20}             # ㅏㅐㅑㅒㅓㅔㅕㅖㅣ — 초성이 왼쪽
JUNG_COMB = {9, 10, 11, 14, 15, 16, 19}              # ㅘㅙㅚㅝㅞㅟㅢ — 초성이 왼쪽 위
SURE_STAND, SURE_LIE = 1.6, 2.6                      # 사진 쪽: 폭/굵기가 이 사이면 '모름'(잡음에 흔들리지 않게)


def parts(ch):
    """한글 음절 → (초성, 중성, 종성) 번호 · 음절이 아니면 None."""
    c = ord(ch) - 0xAC00
    if not 0 <= c < 11172:
        return None
    return c // 588, (c % 588) // 28, c % 28


def _crop(m):
    ys, xs = np.nonzero(m)
    if not len(xs):
        return None
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _vowel_col(m):
    """세로 모음 기둥(들)의 가장 왼쪽 열 — 글자 높이의 55% 넘게 이어진 세로 잉크는 모음 기둥뿐이다(ㅎ·ㅊ 에는 그런 획이
    없다). ㅐ·ㅔ 처럼 기둥이 둘이면 왼쪽 기둥까지. 못 찾으면 None."""
    H, W = m.shape
    for x in range(int(W * 0.3), W):
        run = cur = 0
        for v in m[:, x]:
            cur = cur + 1 if v else 0
            run = max(run, cur)
        if run >= 0.55 * H:
            return x
    return None


def kkokji_of_mask(m, ch):
    """음절 하나의 잉크 마스크(bool, 크기 아무거나) → (꼭지 폭 ÷ 가로줄 굵기, 꼭지 높이 ÷ 가로줄 굵기) · 못 재면 None.
    ch 는 그 마스크의 글자(초성이 ㅎ·ㅊ 일 때만 잰다)."""
    p = parts(ch)
    if p is None or p[0] not in CHO_KK:
        return None
    m = _crop(np.asarray(m, bool))
    if m is None or m.shape[0] < 16 or m.shape[1] < 12:
        return None
    if p[1] in JUNG_VERT or p[1] in JUNG_COMB:
        col = _vowel_col(m)
        if col is None:
            return None
        m = _crop(m[:, :max(1, col - 1)])
        if m is None:
            return None
    H, W = m.shape
    if p[2]:                                          # 받침이 있으면 초성은 위쪽 6할 안
        m = _crop(m[:int(H * 0.62)])
        if m is None:
            return None
        H, W = m.shape
    wide = m.sum(1) > 0.45 * W
    bar = next((y for y in range(H) if wide[y]), None)
    if bar is None or bar < 2:
        return None
    t = 0
    while bar + t < H and wide[bar + t]:
        t += 1
    top = m[:bar]
    ys, xs = np.nonzero(top)
    if len(xs) < 3:
        return None
    w = xs.max() - xs.min() + 1
    h = ys.max() - ys.min() + 1
    return w / max(1, t), h / max(1, t)


def kind_of(r, sure=False):
    """kkokji_of_mask 의 폭/굵기 → '서' · '누' · None(sure 면 애매한 것은 None)."""
    if r is None:
        return None
    if not sure:
        return "서" if r < 2.0 else "누"
    return "서" if r < SURE_STAND else ("누" if r > SURE_LIE else None)


def render_mask(font, ch, size=200):
    """PIL 폰트로 글자 하나를 그린 잉크 마스크."""
    from PIL import Image, ImageDraw
    f = font.font_variant(size=size)
    img = Image.new("L", (int(size * 1.6), int(size * 1.6)), 0)
    ImageDraw.Draw(img).text((int(size * 0.2), int(size * 1.35)), ch, font=f, fill=255, anchor="ls")
    return np.asarray(img) > 127


def _o_aspect(font, has):
    if not has("으"):
        return None
    m = _crop(render_mask(font, "으"))
    if m is None:
        return None
    H, W = m.shape
    wide = m.sum(1) > 0.6 * W
    rows = [y for y in range(H) if wide[y]]
    if not rows:
        return None
    o = _crop(m[:rows[0]])                             # ㅡ 위 = ㅇ
    if o is None or o.shape[0] < 10:
        return None
    return o.shape[1] / o.shape[0]


def _slant(font, has):
    if not has("이"):
        return None
    m = _crop(render_mask(font, "이"))
    if m is None:
        return None
    H, W = m.shape
    xs, ys = [], []
    right = m[:, W // 2:]
    for y in range(int(H * 0.15), int(H * 0.85)):
        c = np.flatnonzero(right[y])
        if len(c):
            xs.append(c.mean()); ys.append(y)
    if len(xs) < 10:
        return None
    a = np.polyfit(ys, xs, 1)[0]                       # 아래로 갈수록 x 가 줄면(왼쪽) 오른쪽으로 누운 것
    return float(np.degrees(np.arctan(-a)))


def font_profile(font, has):
    """깨끗한 폰트 → dict(kk_h, kk_c: '서'/'누'/None, kk_r: 폭/굵기(ㅎ), o_aspect, slant)."""
    out = dict(kk_h=None, kk_c=None, kk_r=None, o_aspect=None, slant=None)
    for key, ch in (("kk_h", "흐"), ("kk_c", "츠")):
        if has(ch):
            r = kkokji_of_mask(render_mask(font, ch), ch)
            if r is not None:
                out[key] = kind_of(r[0])
                if key == "kk_h":
                    out["kk_r"] = float(r[0])
    out["o_aspect"] = _o_aspect(font, has)
    out["slant"] = _slant(font, has)
    return out


def line_kkokji(glyphs):
    """사진 줄의 글자들 [(글자, 마스크)] → ('서'/'누'/None, 잰 글자 수, 같은 쪽 비율). 확실한 글자만 모아 다수결."""
    votes = []
    for ch, m in glyphs:
        r = kkokji_of_mask(m, ch)
        k = kind_of(r[0], sure=True) if r is not None else None
        if k:
            votes.append(k)
    if not votes:
        return None, 0, 0.0
    s = votes.count("서")
    k = "서" if s * 2 > len(votes) else ("누" if s * 2 < len(votes) else None)
    return k, len(votes), max(s, len(votes) - s) / len(votes)
