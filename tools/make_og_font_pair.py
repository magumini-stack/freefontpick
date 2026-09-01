# -*- coding: utf-8 -*-
"""조합 찾기 페이지의 공유 카드 이미지(1200×630)를 그린다.

메인 og 이미지(static/og-image-v3.png)와 같은 결로 맞춘다 —
같은 바탕색·남색, 어깨글 / 큰 글자 / 알약 / 아래 한 줄의 네 단.

가운데 정사각형 안에만 그린다
----------------------------
인스타·카톡은 가로 카드를 1:1로 잘라 쓰는 자리가 있다. 1200×630을 정사각형으로
자르면 가운데 630×630만 남으므로, 글자를 그 안에 다 넣는다. 여백까지 치면
가로 550px 안이다. 아래 SAFE 로 검사한다.

다시 그릴 때
-----------
    python tools/make_og_font_pair.py

서체 파일은 운영에서 내려받는다(없으면 자동으로 받는다). 메인 og 이미지는
만든 방법이 안 남아 있어 글자 하나 고치는 데 원본 서체를 아홉 벌 겹쳐 재는
일부터 해야 했다 — 그 일을 반복하지 않으려고 이 파일을 남긴다.
"""
import io
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, 'tools', '_ogfonts')
OUT = os.path.join(ROOT, 'static', 'og-font-pair.png')
# 사이트 주소 — app/site.py 와 같은 환경변수를 본다.
# 도메인을 옮기면 SITE_URL 을 주고 돌린다.
BASE = os.getenv("SITE_URL", "https://freefontpick.co.kr").rstrip("/")
HOST = BASE.split("://", 1)[-1]   # 이미지에 글자로 찍을 때 쓴다

W, H = 1200, 630
BG = (253, 245, 241)
NAVY = (22, 52, 137)
INK = (51, 51, 50)
WHITE = (255, 255, 255)

# 가운데 정사각형(630×630)에서 여백을 뺀 폭. 이 안에 다 들어가야 잘려도 안전하다.
SAFE = 550
CX = W // 2


def fetch(font_id, weight, name):
    """번들 폰트를 내려받아 ttf로 둔다. 이미 있으면 그대로 쓴다."""
    os.makedirs(FONT_DIR, exist_ok=True)
    path = os.path.join(FONT_DIR, '%d-%d.ttf' % (font_id, weight))
    if not os.path.exists(path):
        from fontTools.ttLib import TTFont
        url = '%s/api/fonts/%d/file' % (BASE, font_id)
        if weight != 400:
            url += '?weight=%d' % weight
        raw = urllib.request.urlopen(url, timeout=180).read()
        f = TTFont(io.BytesIO(raw))
        f.flavor = None
        f.save(path)
        print('  받음 %s' % name)
    return path


# 에스코어드림 — 메인 og 이미지와 가장 가까운 글자꼴(겹침 0.77로 아홉 벌 중 1위)
UI900 = fetch(61, 900, '에스코어드림 900')
UI800 = fetch(61, 800, '에스코어드림 800')

im = Image.new('RGB', (W, H), BG)
d = ImageDraw.Draw(im)


def fit(path, text, target):
    """SAFE 안에 들어가는 가장 큰 크기를 찾는다."""
    lo, hi, best = 10, 200, None
    probe = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    for size in range(lo, hi):
        f = ImageFont.truetype(path, size)
        if probe.textlength(text, font=f) <= target:
            best = (f, size)
        else:
            break
    return best


def center(text, font, cy, fill):
    """잉크 상자 기준으로 가운데. anchor를 쓰면 글꼴의 빈 여백까지 세어 밀린다."""
    bb = font.getbbox(text)
    d.text((CX - (bb[0] + bb[2]) / 2, cy - (bb[1] + bb[3]) / 2), text, font=font, fill=fill)
    return bb[2] - bb[0]


# ── ① 어깨글 ────────────────────────────────────────────────
f_kick, _ = fit(UI800, '폰트픽', 200)
f_kick = ImageFont.truetype(UI800, 30)
w_kick = center('폰트픽', f_kick, 176, NAVY)

# ── ② 큰 글자 ───────────────────────────────────────────────
f_big, size_big = fit(UI900, '폰트 조합 찾기', SAFE)
w_big = center('폰트 조합 찾기', f_big, 262, INK)

# ── ③ 알약 ──────────────────────────────────────────────────
LEAD = '제목·본문에 어울리는 무료 폰트 세 가지'
f_lead = ImageFont.truetype(UI800, 27)
w_lead = d.textlength(LEAD, font=f_lead)
pw, ph = w_lead + 76, 62
d.rounded_rectangle([CX - pw / 2, 344, CX + pw / 2, 344 + ph], radius=ph // 2, fill=NAVY)
center(LEAD, f_lead, 344 + ph / 2, WHITE)

# ── ④ 세 자리 ───────────────────────────────────────────────
# 메인 og 이미지의 아이콘 세 칸과 같은 자리. 이 페이지가 다루는 세 단이다.
f_role = ImageFont.truetype(UI800, 25)
roles = ['타이틀', '서브타이틀', '본문']
gap, sep = 34, 1
widths = [d.textlength(r, font=f_role) for r in roles]
total = sum(widths) + gap * 2 * len(roles) - gap * 2 + sep * 2
x = CX - total / 2
for i, r in enumerate(roles):
    bb = f_role.getbbox(r)
    d.text((x - bb[0], 470 - (bb[1] + bb[3]) / 2), r, font=f_role, fill=INK)
    x += widths[i]
    if i < len(roles) - 1:
        x += gap
        d.line([(x, 458), (x, 484)], fill=(228, 216, 210), width=sep)
        x += gap

# ── ⑤ 주소 ──────────────────────────────────────────────────
f_url = ImageFont.truetype(UI800, 24)
w_url = center(HOST, f_url, 545, NAVY)

im.save(OUT, optimize=True)

print('\n저장 %s' % OUT)
print('  %dx%d · %.0fKB' % (W, H, os.path.getsize(OUT) / 1024))
print('\n가운데 정사각형(폭 %d) 안에 들어가는지' % SAFE)
for label, w in [('어깨글', w_kick), ('큰 글자(%dpx)' % size_big, w_big),
                 ('알약', pw), ('세 자리', total), ('주소', w_url)]:
    print('  %-16s %4.0fpx  %s' % (label, w, 'OK' if w <= SAFE else '★ 넘침'))
