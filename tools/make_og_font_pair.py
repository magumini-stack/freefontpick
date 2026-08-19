# -*- coding: utf-8 -*-
"""조합 찾기 페이지의 og 이미지(1200×630).

이 페이지가 하는 일이 "세 폰트를 한 자리에 앉혀 본다"이므로, 설명 문구를
쓰는 대신 **실제로 그렇게 앉힌 화면**을 그린다. 카톡·인스타에서 카드는
작게 뜨므로 글자를 크게, 요소는 적게 둔다.

쓰는 서체는 페이지가 처음 열릴 때 나오는 그 세 벌이다 —
여기어때 잘난체 / 아리따 부리 / Noto Sans CJK KR.
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image, ImageDraw, ImageFont

SC = r'C:\Users\jypark\AppData\Local\Temp\claude\C--Users-jypark-Desktop\597320b7-bd1a-4b9c-8272-2cb6f8262ef2\scratchpad'
OUT = r'C:\Users\jypark\Desktop\freefontpick\static\og-font-pair.png'

W, H = 1200, 630
BG = (253, 245, 241)          # 메인 og와 같은 바탕
NAVY = (22, 52, 137)
INK = (26, 26, 24)
MUTED = (138, 133, 129)
CARD = (255, 255, 255)

UI = SC + r'\fonts\61-800.ttf'          # 에스코어드림 800 — 라벨용
F_TITLE = SC + r'\fonts\og-62.ttf'      # 여기어때 잘난체
F_SUB = SC + r'\fonts\og-59.ttf'        # 아리따 부리
F_BODY = SC + r'\fonts\og-10.ttf'       # Noto Sans CJK KR

im = Image.new('RGB', (W, H), BG)
d = ImageDraw.Draw(im)


def ink(text, font):
    """글자가 실제로 차지하는 상자. anchor를 쓰면 글꼴의 빈 여백까지 세어
    눈으로 볼 때 가운데가 밀린다."""
    return font.getbbox(text)


def draw_at(x, y_center, text, font, fill):
    bb = ink(text, font)
    d.text((x - bb[0], y_center - (bb[1] + bb[3]) / 2), text, font=font, fill=fill)
    return bb[2] - bb[0]


# ── 위 어깨글 ────────────────────────────────────────────────
f_kick = ImageFont.truetype(UI, 30)
draw_at(72, 70, '폰트픽 · 폰트 조합 찾기', f_kick, NAVY)

# ── 견본 카드 — 실제 조합 화면을 그대로 옮긴다 ──────────────
CX, CY, CW, CH = 72, 116, W - 144, 372
d.rounded_rectangle([CX + 5, CY + 7, CX + CW + 5, CY + CH + 7],
                    radius=18, fill=(243, 232, 226))      # 그림자
d.rounded_rectangle([CX, CY, CX + CW, CY + CH], radius=18, fill=CARD)

f_role = ImageFont.truetype(UI, 20)
f_t = ImageFont.truetype(F_TITLE, 78)
f_s = ImageFont.truetype(F_SUB, 38)
f_b = ImageFont.truetype(F_BODY, 27)

LX = CX + 52          # 글이 시작하는 자리
RX = CX + CW - 52     # 역할 라벨이 끝나는 자리
rows = [
    (196, '타이틀', '겨울 정원 산책', f_t),
    (292, '서브타이틀', '12월 6일 토요일 오후 2시 · 서울식물원', f_s),
    (368, '본문', '지나가면서, 대개는 비스듬히 보는 자리.', f_b),
]
for y, role, text, font in rows:
    draw_at(LX, y, text, font, INK)
    bb = ink(role, f_role)
    d.text((RX - (bb[2] - bb[0]) - bb[0], y - (bb[1] + bb[3]) / 2),
           role, font=f_role, fill=MUTED)

# 본문 아래 한 줄 더 — 세 단이 한 덩어리로 보이게
draw_at(LX, 408, '굵기보다 글자통의 크기가 읽히는 거리를 정합니다.', f_b, INK)

# ── 아래 한 줄 ───────────────────────────────────────────────
f_lead = ImageFont.truetype(UI, 36)
f_url = ImageFont.truetype(UI, 26)
draw_at(72, 552, '제목·본문에 어울리는 무료 폰트 세 가지', f_lead, INK)
u = 'freefontpick.co.kr'
bb = ink(u, f_url)
d.text((W - 72 - (bb[2] - bb[0]) - bb[0], 552 - (bb[1] + bb[3]) / 2),
       u, font=f_url, fill=NAVY)

im.save(OUT, optimize=True)
print('저장 %s  %dx%d  %.0fKB' % (OUT, W, H, os.path.getsize(OUT) / 1024))
