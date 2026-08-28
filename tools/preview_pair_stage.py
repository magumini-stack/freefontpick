"""폰트 조합 찾기 캔버스를 그림으로 미리 그려 본다.

왜 필요한가
----------
이 화면의 글 자리는 배경 사진의 빈 곳에 맞춰야 하는데, 값만 보고 고치면
글자가 인물이나 장식 위에 얹혔는지 알 수 없다. 실제로 그렇게 고쳤다가
"콩알만해졌다 / 배치가 이상하다"는 말을 들었다.

그래서 font-pair.html 의 CSS 값을 **그대로 읽어** 같은 계산으로 그린다.
값을 여기 옮겨 적지 않는 것이 요점이다 — 옮겨 적으면 미리보기만 맞고
실제 화면은 틀리는, 가장 나쁜 상태가 된다.

브라우저와 다른 점: 글꼴이 실제 추천 폰트가 아니라 한 가지로 고정이고,
줄바꿈 규칙도 완전히 같지는 않다. 보려는 것은 '글이 어디에 앉는가'다.

    python tools/preview_pair_stage.py
    → static/pair-bg/_preview_{틀이름}.png (검사용, 커밋하지 않는다)
"""
import io
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "static" / "font-pair.html"
BG = ROOT / "static" / "pair-bg"
UI_FONT = ROOT / "fonts" / "font-101.woff2"          # 프리텐다드 — 자리만 본다

W = 916                     # .fp-stage max-width
H = round(W * 9 / 16)
CQW = W / 100.0


def css_block(name: str) -> str:
    """.mk-{name}{...} 한 덩어리."""
    m = re.search(r"\.mk-%s\{(.*?)\}" % name, HTML.read_text(encoding="utf-8"), re.S)
    if not m:
        raise SystemExit(".mk-%s 규칙을 못 찾았다" % name)
    return m.group(1)


def num(block: str, prop: str, default=None):
    m = re.search(r"%s:\s*([\d.]+)cqw" % prop, block)
    if m:
        return float(m.group(1))
    if default is None:
        raise SystemExit("%s 값을 못 찾았다" % prop)
    return default


def padding(block: str):
    m = re.search(r"padding:\s*([^;}]+)", block)
    if not m:
        return (7, 7, 7, 7)
    v = [float(x) for x in re.findall(r"([\d.]+)cqw", m.group(1))]
    if len(v) == 1:
        return (v[0],) * 4
    if len(v) == 2:
        return (v[0], v[1], v[0], v[1])
    if len(v) == 3:
        return (v[0], v[1], v[2], v[1])
    return tuple(v[:4])                      # 위 오른쪽 아래 왼쪽


def wrap(draw, text, font, maxw):
    out = []
    for para in text.split("\n"):
        line = ""
        for ch in para:
            if draw.textlength(line + ch, font=font) <= maxw:
                line += ch
            else:
                out.append(line)
                line = ch
        out.append(line)
    return out


def build(name, key, samples):
    block = css_block(name)
    pt, pr, pb, pl = padding(block)
    t_sz = num(block, "--b-title") * CQW
    s_sz = num(block, "--b-sub") * CQW
    b_sz = num(block, "--b-body") * CQW
    color = re.search(r"color:\s*(#[0-9A-Fa-f]{6})", block)
    color = color.group(1) if color else "#222222"
    centered = "text-align:center" in block
    center_v = "justify-content:center" in block

    im = Image.open(BG / (name + ".webp")).convert("RGB").resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(im, "RGBA")

    x0, x1 = pl * CQW, W - pr * CQW
    boxw = x1 - x0
    ft = ImageFont.truetype(str(UI_FONT), round(t_sz))
    fs = ImageFont.truetype(str(UI_FONT), round(s_sz))
    fb = ImageFont.truetype(str(UI_FONT), round(b_sz))

    tl = wrap(d, samples[0], ft, boxw)
    sl = wrap(d, samples[1], fs, boxw)
    bl = wrap(d, samples[2], fb, boxw)

    th = len(tl) * t_sz * 1.16
    sh = len(sl) * s_sz * 1.45
    gap = 2.4 * CQW
    body_abs = "fp-blk-body{position:absolute" in \
        re.sub(r"\s+", "", HTML.read_text(encoding="utf-8"))[
            re.sub(r"\s+", "", HTML.read_text(encoding="utf-8")).find(".mk-" + name):][:600]
    bh = 0 if body_abs else len(bl) * b_sz * 1.75 + gap

    total = th + gap + sh + bh
    y = pt * CQW
    if center_v:
        avail = H - (pt + pb) * CQW
        y = pt * CQW + max(0, (avail - total) / 2)

    def put(lines, font, size, yy, lh, alpha=255):
        for ln in lines:
            w = d.textlength(ln, font=font)
            xx = x0 + (boxw - w) / 2 if centered else x0
            d.text((xx, yy), ln, font=font, fill=color + ("%02x" % alpha))
            yy += size * lh
        return yy

    y = put(tl, ft, t_sz, y, 1.16)
    y += gap
    y = put(sl, fs, s_sz, y, 1.45, 200)

    # 글이 놓인 상자를 붉은 선으로 표시 — 사진의 빈 곳과 맞는지 보려는 것
    d.rectangle([x0, pt * CQW, x1, H - pb * CQW], outline=(220, 60, 60, 130), width=2)
    d.text((6, 4), "%s / %s  제목 %.1fcqw" % (name, key, num(block, "--b-title")),
           font=ImageFont.truetype(str(UI_FONT), 15), fill=(220, 60, 60, 255))

    out = BG / ("_preview_%s.png" % name)
    im.save(out)
    return out


def main():
    sys.path.insert(0, str(ROOT))
    from app.pair_specimens import PAIR_CATEGORIES

    for c in PAIR_CATEGORIES:
        if not c.get("mockup"):
            continue
        p = build(c["mockup"], c["key"], c["ko"])
        print("  %s" % p)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
