"""'본문 · 읽기' 자리의 배경을 코드로 그린다 (static/pair-bg/magazine.webp).

다른 다섯 자리는 사진을 받아 쓰지만 이 자리만 직접 그린다. 이유가 있다.

왜 선을 그림에 넣지 않나
----------------------
앞서 쓰던 사진에는 가로줄이 그어져 있었고, 글을 그 줄에 맞추려다 본문이
위로 끌려 올라갔다. 그림에 박힌 선은 글이 한 줄만 늘어나도 어긋난다.
그래서 이 배경에는 선을 하나도 넣지 않는다. 단 나누는 선도, 제목 아래
선도 전부 CSS 가 긋는다 — 그러면 선이 글을 따라간다.

여기서 그리는 것은 '종이'뿐이다
---------------------------
읽는 자리라 바탕이 조용해야 한다. 무늬가 있으면 그게 곧 본문 위의 잡음이
된다. 그래서 담는 것은 네 가지뿐이다.
  1. 미색 종이 바탕 — 위가 조금 밝고 아래로 갈수록 아주 조금 따뜻해진다
  2. 아주 고운 결 — 균일한 색면은 화면에서 '빈 칸'으로 보인다
  3. 바깥으로 갈수록 살짝 어두워지는 그늘 — 종이 한 장이 놓인 느낌
  4. 오른쪽 아래 아주 옅은 쪽번호 자리 — 매거진 지면의 표시

    python tools/make_pair_bg_magazine.py
"""
import io
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "pair-bg" / "magazine.webp"

W, H = 1600, 900
TOP = (253, 251, 246)      # 위쪽 종이색
BOTTOM = (247, 242, 233)   # 아래쪽 — 아주 조금 따뜻하게


def paper() -> Image.Image:
    """위아래로 아주 옅게 변하는 종이 바탕."""
    g = Image.new("RGB", (1, H))
    px = g.load()
    for y in range(H):
        t = y / (H - 1)
        px[0, y] = tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
    return g.resize((W, H), Image.BILINEAR)


def grain(im: Image.Image, sigma: float = 11.0, amount: float = 0.085) -> Image.Image:
    """고운 결. 균일한 색면은 화면에서 '덜 그려진 칸'처럼 보인다.

    세게 넣으면 본문 글자와 싸우므로 아주 옅게만 얹는다.
    """
    n = Image.effect_noise((W, H), sigma).convert("L")
    n = n.filter(ImageFilter.GaussianBlur(0.4))
    return Image.blend(im, ImageChops.overlay(im, n.convert("RGB")), amount)


def vignette(im: Image.Image, strength: float = 0.16) -> Image.Image:
    """가장자리만 아주 살짝 어두워진다 — 종이 한 장이 놓인 느낌.

    가운데는 건드리지 않는다. 글이 앉는 자리라 밝기가 고르게 남아야 한다.

    동심 타원을 겹쳐 그리는 방법을 먼저 썼는데 고리 무늬가 생겨 얼룩처럼
    보였다. 그래서 낮은 해상도에서 픽셀마다 값을 계산하고 키운다 —
    계단이 안 생기고 빠르다.
    """
    sw, sh = 160, 90
    m = Image.new("L", (sw, sh))
    px = m.load()
    for y in range(sh):
        # 가로 방향으로 더 넓게 퍼뜨린다(16:9 라 세로가 먼저 어두워지는 것을 막는다)
        dy = abs(y / (sh - 1) * 2 - 1)
        for x in range(sw):
            dx = abs(x / (sw - 1) * 2 - 1)
            t = max(dx, dy)                 # 사각형에 가까운 감쇠
            # 문턱값(t<0.72 는 0)을 두면 그 자리에 옅은 테두리가 드러난다.
            # 실제로 보였다. 가운데부터 끝까지 끊기지 않는 곡선으로 바꾼다.
            v = t ** 3.6
            px[x, y] = 255 - round(255 * min(1.0, v))
    m = m.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(40))
    dark = Image.new("RGB", (W, H), (198, 187, 168))
    return Image.composite(im, Image.blend(im, dark, strength), m)


def folio(im: Image.Image) -> Image.Image:
    """오른쪽 아래 쪽번호 자리 — 짧은 선 하나. 글자는 넣지 않는다.

    숫자를 넣으면 '몇 쪽'인지가 거짓말이 되고, 조합을 새로 뽑을 때마다
    같은 숫자가 남아 어색하다. 지면에 있던 흔적만 남긴다.
    """
    d = ImageDraw.Draw(im, "RGBA")
    x1, x2 = round(W * 0.885), round(W * 0.94)
    y = round(H * 0.925)
    d.line([x1, y, x2, y], fill=(150, 136, 114, 70), width=2)
    return im


def main():
    im = paper()
    im = grain(im)
    im = vignette(im)
    im = folio(im)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT, "WEBP", quality=88, method=6)
    print("  %s  %dx%d  %.0f KB" % (OUT, W, H, OUT.stat().st_size / 1024))
    print("  선은 그리지 않았다 — 제목 아래 선과 단 사이 선은 CSS 가 긋는다.")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
