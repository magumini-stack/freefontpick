"""폰트별 og:image(1200x630) 자동 생성.

- 배지("무료폰트 · 상업적 사용 가능") + 폰트명(실제 폰트 파일로 렌더링) +
  "OO 배포" + 하단 "무료폰트 큐레이션-폰트픽" 을 합성한 PNG를 만든다.
- 폰트명은 정사각형(630x630)으로 크롭됐을 때도 그 정사각형 너비의 90%를
  채우도록 폰트 크기를 이분탐색으로 계산한다 (소셜 공유 시 정사각형 썸네일 대비).
- 배지+폰트명+배포처 블록은 하단 워터마크 영역을 제외한 카드 내부 기준으로
  수직 중앙 정렬한다.
- woff2는 Pillow가 직접 못 읽으므로 fontTools로 ttf로 디코딩해서 메모리에서 사용.
- 생성 결과는 디스크에 캐싱하고, 폰트 파일/이름이 바뀌면 캐시가 자동 무효화되도록
  파일 mtime을 캐시 키에 포함한다.
"""
import io
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Font
from .files import FONT_RESOLUTION, font_path, bundled_font_path

router = APIRouter(prefix="/api/fonts", tags=["og-image"])

CACHE_DIR = Path(os.getenv("OGIMAGE_CACHE_DIR", "/app/user_data/og_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1200, 630
BG = "#FAFAF7"
CARD_BG = "#FFFFFF"
BORDER = "#E5E5E0"
TEXT_COLOR = "#1A1A1A"
MUTED = "#6B6B6B"
ACCENT = "#FF5C35"

# UI 텍스트(배지/배포처/워터마크)용 폰트 — 이미 번들된 Noto Sans CJK KR(시드 id=10)을 재사용.
# 별도 시스템 폰트나 추가 에셋 없이도 배포 환경에서 항상 존재가 보장된다.
_UI_FONT_ID = 10


def _resolve_font_file(font_id: int) -> Path | None:
    resolved = FONT_RESOLUTION.get(font_id)
    if resolved and Path(resolved[0]).exists():
        return Path(resolved[0])
    p = font_path(font_id)
    if p.exists():
        return p
    bp = bundled_font_path(font_id)
    if bp.exists():
        return bp
    return None


def _woff2_to_fontobject(path: Path):
    """woff2/ttf/otf 파일을 Pillow가 읽을 수 있는 in-memory 폰트 바이트로 변환."""
    from fontTools.ttLib import TTFont

    with open(path, "rb") as f:
        head = f.read(4)
    buf = io.BytesIO()
    if head == b"wOF2":
        tt = TTFont(str(path))
        tt.flavor = None
        tt.save(buf)
    else:
        buf.write(path.read_bytes())
    buf.seek(0)
    return buf


def _generate(font: Font) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    pad = 60
    d.rounded_rectangle([pad, pad, W - pad, H - pad], radius=28, fill=CARD_BG, outline=BORDER, width=2)

    ui_font_file = _resolve_font_file(_UI_FONT_ID)
    ui_bold_bytes = None
    ui_reg_bytes = None
    if ui_font_file:
        try:
            ui_bold_bytes = _woff2_to_fontobject(ui_font_file)
            ui_reg_bytes = _woff2_to_fontobject(ui_font_file)
        except Exception:
            ui_bold_bytes = None
            ui_reg_bytes = None

    def _ui_font(size, bytes_buf):
        if bytes_buf is not None:
            bytes_buf.seek(0)
            try:
                return ImageFont.truetype(bytes_buf, size)
            except Exception:
                pass
        # 최후 폴백: PIL 기본 폰트 (한글은 깨지지만 서비스 중단은 방지)
        return ImageFont.load_default()

    sub_font = _ui_font(26, ui_reg_bytes)
    badge_font = _ui_font(22, ui_bold_bytes)

    cx = W // 2

    def center_text(y, text, font, fill):
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text((cx - tw / 2, y), text, font=font, fill=fill)
        return th

    # 폰트명 렌더링용 실제 폰트 로드 (실패 시 UI 폰트로 폴백)
    font_file = _resolve_font_file(font.id)
    name_font_bytes = None
    if font_file:
        try:
            name_font_bytes = _woff2_to_fontobject(font_file)
        except Exception:
            name_font_bytes = None

    font_name_text = font.name

    def load_name_font(size):
        if name_font_bytes is not None:
            name_font_bytes.seek(0)
            try:
                return ImageFont.truetype(name_font_bytes, size)
            except Exception:
                pass
        return _ui_font(size, ui_bold_bytes)

    square_size = min(W, H)
    target_w = square_size * 0.9

    def measure_w(size):
        f = load_name_font(int(size))
        bbox = d.textbbox((0, 0), font_name_text, font=f)
        return bbox[2] - bbox[0]

    lo, hi = 10, 300
    for _ in range(24):
        mid = (lo + hi) / 2
        if measure_w(mid) < target_w:
            lo = mid
        else:
            hi = mid
    name_size = max(int(lo), 10)
    name_font = load_name_font(name_size)
    name_bbox = d.textbbox((0, 0), font_name_text, font=name_font)
    name_h = name_bbox[3] - name_bbox[1]

    # 상단 배지
    badge_text = "무료폰트 · 상업적 사용 가능"
    bbox = d.textbbox((0, 0), badge_text, font=badge_font)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    badge_pad_x, badge_pad_y = 18, 10
    badge_box_h = bh + badge_pad_y * 2

    sub_text = f"{font.maker or ''} 배포"
    sub_bbox = d.textbbox((0, 0), sub_text, font=sub_font)
    sub_h = sub_bbox[3] - sub_bbox[1]

    gap1, gap2 = 55, 40
    block_h = badge_box_h + gap1 + name_h + gap2 + sub_h

    # 하단 워터마크 영역을 제외한 카드 내부를 기준으로 배지+폰트명+배포처 블록을 수직 중앙 정렬
    watermark_reserved = 90
    usable_top, usable_bottom = pad, (H - pad) - watermark_reserved
    by = usable_top + (usable_bottom - usable_top - block_h) / 2

    bx = cx - (bw + badge_pad_x * 2) / 2
    d.rounded_rectangle([bx, by, bx + bw + badge_pad_x * 2, by + badge_box_h], radius=100, fill="#FFF0EC")
    d.text((bx + badge_pad_x, by + badge_pad_y - 4), badge_text, font=badge_font, fill=ACCENT)

    # 폰트명 (실제 폰트로 렌더링)
    name_y = by + badge_box_h + gap1
    center_text(name_y, font_name_text, name_font, TEXT_COLOR)

    # 배포처
    sub_y = name_y + name_h + gap2
    center_text(sub_y, sub_text, sub_font, MUTED)

    # 하단 워터마크
    center_text(H - pad - 60, "무료폰트 큐레이션-폰트픽", sub_font, ACCENT)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _cache_key(font: Font) -> str:
    font_file = _resolve_font_file(font.id)
    mtime = int(font_file.stat().st_mtime) if font_file else 0
    return f"font-{font.id:03d}-{mtime}.png"


@router.get("/{font_id}/og-image.png")
def get_og_image(font_id: int, db: Session = Depends(get_db)):
    from fastapi.responses import Response

    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    cache_path = CACHE_DIR / _cache_key(font)
    headers = {"Cache-Control": "public, max-age=86400"}
    if cache_path.exists():
        return FileResponse(cache_path, media_type="image/png", headers=headers)

    try:
        data = _generate(font)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"이미지 생성 실패: {e}")

    try:
        cache_path.write_bytes(data)
    except Exception:
        pass

    if cache_path.exists():
        return FileResponse(cache_path, media_type="image/png", headers=headers)
    return Response(content=data, media_type="image/png", headers=headers)
