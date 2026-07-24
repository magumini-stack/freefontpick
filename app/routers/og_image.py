"""폰트별 og:image(1200x630) 자동 생성.

- 폰트명(실제 폰트 파일로 렌더링) + "OO 배포" + 하단 "폰트픽" 로고 마크를
  합성한 PNG를 만든다.
- 폰트명은 정사각형(630x630)으로 크롭됐을 때도 그 정사각형 너비의 90%를
  채우도록 폰트 크기를 이분탐색으로 계산한다 (소셜 공유 시 정사각형 썸네일 대비).
- woff2는 Pillow가 직접 못 읽으므로 fontTools로 ttf로 디코딩해서 메모리에서 사용.
  이때 폰트 전체(수천~1만+ 글리프의 CJK 폰트도 흔함)를 통째로 파싱/재저장하면
  메모리·CPU 부담이 커서 컨테이너가 죽는(502) 경우가 있었다 — 실제로 필요한 건
  폰트명에 쓰인 글자 몇 개뿐이므로, fontTools.subset으로 그 글자들만 추려낸
  경량 폰트로 축소한 뒤 렌더링한다.
- 생성 결과는 디스크에 캐싱하고, 폰트 파일/이름이 바뀌면 캐시가 자동 무효화되도록
  파일 mtime을 캐시 키에 포함한다.
- 2026-07: 생성은 요청 1건당 약 +58MB(실측)를 순간적으로 잡아먹는다. 이 엔드포인트는
  동기 함수라 FastAPI가 스레드풀에서 병렬 실행하므로, 캐시가 비어있는 상태에서
  크롤러 여러 대가 서로 다른 폰트를 동시에 요청하면 메모리가 배수로 튀어 컨테이너가
  죽는다(502). 그래서 생성 구간 전체를 프로세스 단위 락으로 감싸 항상 한 번에
  하나만 만들도록 직렬화한다. 캐시가 채워진 뒤에는 락에 들어가지 않고 파일만 내보내므로
  평상시 성능에는 영향이 없다.
    실측(동시 요청 수 → 프로세스 최대 메모리):
      2건  127MB → 105MB / 4건  220MB → 140MB / 8건  403MB → 187MB
- 캐시를 미리 채워두면 크롤러가 생성을 유발할 일 자체가 없어지므로,
  관리자용 예열 엔드포인트(POST /api/fonts/og-warm)를 함께 제공한다.
"""
import gc
import io
import os
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
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
ACCENT = "#1E3A8A"

# UI 텍스트(배포처/로고마크)용 폰트 — 이미 번들된 Noto Sans CJK KR(시드 id=10)을 재사용.
# 별도 시스템 폰트나 추가 에셋 없이도 배포 환경에서 항상 존재가 보장된다.
_UI_FONT_ID = 10

# 레이아웃/렌더링 로직이 바뀔 때마다 올려서 기존 캐시를 무효화한다.
_CACHE_VERSION = 5


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
    """woff2/ttf/otf 파일을 Pillow가 읽을 수 있는 in-memory 폰트 바이트로 변환.

    UI 폰트(배포처/로고마크 — 항상 같은 번들 폰트 하나만 씀)용 경량 경로.
    글자 수가 적고 매 요청 재사용되는 성격이라 서브셋 없이 그대로 변환한다.
    """
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


def _subset_font_to_fontobject(path: Path, text: str):
    """폰트 파일에서 text에 쓰인 글자에 필요한 글리프만 추려서 변환.

    사용자가 업로드하는 폰트는 글리프 수천~1만+ 개짜리 CJK 폰트인 경우가 흔한데,
    og:image에는 폰트명 몇 글자만 실제 폰트로 렌더링하면 되므로 그 글자들만
    남기고 나머지는 버린다. 폰트 전체를 통째로 파싱/재저장할 때보다 메모리·CPU
    사용량이 훨씬 작아서, 큰 폰트에서 서버가 죽는(502) 문제를 막아준다.
    """
    from fontTools.ttLib import TTFont
    from fontTools import subset

    tt = TTFont(str(path), fontNumber=0, lazy=True)
    tt.flavor = None

    options = subset.Options()
    options.desubroutinize = False
    options.hinting = False
    options.notdef_glyph = True
    options.notdef_outline = False
    options.recalc_bounds = False
    options.recalc_timestamp = False
    options.layout_features = []
    options.legacy_kern = False
    options.ignore_missing_glyphs = True
    options.ignore_missing_unicodes = True
    options.name_IDs = []
    options.drop_tables += ["GSUB", "GPOS", "GDEF", "kern", "DSIG"]

    subsetter = subset.Subsetter(options=options)
    # notdef + 공백 + 실제로 그릴 글자들만 남긴다
    subsetter.populate(text=(text or "") + " ")
    subsetter.subset(tt)

    buf = io.BytesIO()
    tt.save(buf)
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
            # 같은 파일을 두 번 디코딩할 필요 없이 한 번 변환해 재사용
            ui_bold_bytes = _woff2_to_fontobject(ui_font_file)
            ui_reg_bytes = io.BytesIO(ui_bold_bytes.getvalue())
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

    cx = W // 2

    def center_text(y, text, font, fill):
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text((cx - tw / 2, y), text, font=font, fill=fill)
        return th

    def center_logo_mark(y):
        """사이트 좌상단 로고("폰트픽" + 포인트 사각 점)와 동일한 스타일의 하단 워터마크."""
        text = "폰트픽"
        logo_size = 32
        logo_font = _ui_font(logo_size, ui_bold_bytes)
        bbox = d.textbbox((0, 0), text, font=logo_font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        dot = round(logo_size * 0.35)
        gap = round(logo_size * 0.28)
        total_w = tw + gap + dot

        start_x = cx - total_w / 2
        d.text((start_x, y), text, font=logo_font, fill=TEXT_COLOR)

        dot_x0 = start_x + tw + gap
        dot_y0 = y + th - dot - round(logo_size * 0.06)
        d.rounded_rectangle([dot_x0, dot_y0, dot_x0 + dot, dot_y0 + dot], radius=2, fill=ACCENT)
        return th

    font_name_text = font.name

    # 폰트명 렌더링용 실제 폰트 로드 (실패 시 UI 폰트로 폴백)
    # 폰트명에 쓰인 글자만 서브셋해서 큰 CJK 폰트에서도 가볍게 처리한다.
    font_file = _resolve_font_file(font.id)
    name_font_bytes = None
    if font_file:
        try:
            name_font_bytes = _subset_font_to_fontobject(font_file, font_name_text)
        except Exception:
            name_font_bytes = None

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

    sub_text = f"{font.maker or ''} 배포"
    sub_bbox = d.textbbox((0, 0), sub_text, font=sub_font)
    sub_h = sub_bbox[3] - sub_bbox[1]

    gap2 = 40
    block_h = name_h + gap2 + sub_h

    # 하단 로고 마크 영역을 제외한 카드 내부를 기준으로 폰트명+배포처 블록을 수직 중앙 정렬
    watermark_reserved = 90
    usable_top, usable_bottom = pad, (H - pad) - watermark_reserved
    by = usable_top + (usable_bottom - usable_top - block_h) / 2

    # 폰트명 (실제 폰트로 렌더링)
    name_y = by
    center_text(name_y, font_name_text, name_font, TEXT_COLOR)

    # 배포처
    sub_y = name_y + name_h + gap2
    center_text(sub_y, sub_text, sub_font, MUTED)

    # 하단 로고 마크 (사이트 좌상단 로고와 동일 스타일)
    center_logo_mark(H - pad - 62)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _cache_key(font: Font) -> str:
    font_file = _resolve_font_file(font.id)
    mtime = int(font_file.stat().st_mtime) if font_file else 0
    return f"font-{font.id:03d}-v{_CACHE_VERSION}-{mtime}.png"


# 생성 직렬화용 락 — 워커 프로세스당 하나.
# 이미지 생성은 순간 메모리 사용량이 커서(실측 +58MB) 동시에 여러 건이 돌면
# 512MB 컨테이너도 넘길 수 있다. 캐시 히트 경로는 락을 타지 않는다.
_GEN_LOCK = threading.Lock()


def _ensure_cached(font: Font) -> tuple[Path, bytes | None]:
    """캐시된 파일 경로를 보장한다. 없으면 락을 잡고 하나만 생성한다.

    반환: (캐시경로, 폴백데이터)
      - 정상 캐시 시 폴백데이터는 None
      - 디스크 쓰기에 실패하면 경로는 존재하지 않고 폴백데이터에 PNG 바이트가 담긴다
    """
    cache_path = CACHE_DIR / _cache_key(font)
    if cache_path.exists():
        return cache_path, None

    with _GEN_LOCK:
        # 락을 기다리는 동안 다른 요청이 같은 이미지를 만들었을 수 있다.
        if cache_path.exists():
            return cache_path, None
        try:
            data = _generate(font)
            try:
                cache_path.write_bytes(data)
            except Exception:
                return cache_path, data
        finally:
            # 생성 과정에서 잡힌 폰트 파싱 객체들을 즉시 회수(실측 약 8MB 반환).
            # 생성이 예외로 끝난 경우에도 반드시 돌려준다.
            gc.collect()
    return cache_path, None


@router.get("/{font_id}/og-image.png")
def get_og_image(font_id: int, db: Session = Depends(get_db)):
    from fastapi.responses import Response

    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    headers = {"Cache-Control": "public, max-age=86400"}
    try:
        cache_path, fallback = _ensure_cached(font)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"이미지 생성 실패: {e}")

    if cache_path.exists():
        return FileResponse(cache_path, media_type="image/png", headers=headers)
    return Response(content=fallback or b"", media_type="image/png", headers=headers)


@router.post("/og-warm")
def warm_og_cache(
    limit: int = 20,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """OG 이미지 캐시 예열 — 아직 만들어지지 않은 것들을 순차로 생성한다.

    폰트를 새로 추가한 뒤 한 번 호출해두면, 이후 검색엔진 크롤러가 몰려와도
    이미 만들어진 파일만 나가므로 생성으로 인한 메모리 스파이크가 발생하지 않는다.

    전체를 한 요청에서 처리하면 응답 시간이 수 분대가 되어 타임아웃이 나므로,
    limit개씩 끊어서 처리하고 남은 개수를 함께 돌려준다.
    remaining이 0이 될 때까지 반복 호출하면 된다.
    """
    limit = max(1, min(limit, 50))

    fonts = db.query(Font).order_by(Font.id).all()
    pending = [f for f in fonts if not (CACHE_DIR / _cache_key(f)).exists()]

    created, failed = [], []
    for font in pending[:limit]:
        try:
            _ensure_cached(font)
            created.append(font.id)
        except Exception as e:
            failed.append({"id": font.id, "name": font.name, "error": str(e)})

    return {
        "total": len(fonts),
        "created": created,
        "failed": failed,
        "remaining": len(pending) - len(created),
    }
