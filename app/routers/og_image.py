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
import shutil
import threading
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..models import Font
from .files import FONT_RESOLUTION, font_path, bundled_font_path, resolve_zip

router = APIRouter(prefix="/api/fonts", tags=["og-image"])
# 용도 허브 카드는 경로가 달라 라우터를 하나 더 둔다 (main.py에서 함께 등록).
hub_router = APIRouter(prefix="/api/use-cases", tags=["og-image"])

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
_CACHE_VERSION = 6
# 허브 카드는 폰트 카드와 레이아웃이 달라 버전을 따로 둔다 — 한쪽을 손봤다고
# 다른 쪽 캐시 수백 장을 통째로 버릴 이유가 없다.
_HUB_CACHE_VERSION = 1


# 배포용 ZIP 에서 꺼낸 폰트를 두는 자리.
_ZIP_FONT_CACHE = CACHE_DIR / "zipfonts"
_FONT_EXTS = (".ttf", ".otf")


def _font_from_zip(font_id: int) -> Path | None:
    """배포용 ZIP 안의 TTF/OTF 를 꺼내 캐시하고 그 경로를 준다.

    구글 폰트 CDN 등 웹폰트로만 미리보기를 제공하는 폰트는 로컬 woff2 가
    없어(has_file=False) 여기까지 내려온다. 그대로 두면 UI 폰트로 폴백해
    "폰트 소개 카드에 정작 그 폰트가 아닌 글씨가 나가는" 상태가 된다.
    다운로드용 ZIP 안에는 원본 TTF/OTF 가 들어 있으니 그것을 쓴다.
    (CDN 을 직접 받아오지 않는다 — OG 생성 중에 외부 네트워크를 타면
    그쪽이 느리거나 막혔을 때 카드 생성이 통째로 멈춘다.)
    """
    stem = f"font-{font_id:03d}"
    for ext in _FONT_EXTS:
        cached = _ZIP_FONT_CACHE / (stem + ext)
        if cached.is_file():
            return cached

    zp = resolve_zip(font_id)
    if not zp:
        return None
    try:
        with zipfile.ZipFile(zp) as z:
            names = [
                n for n in z.namelist()
                if n.lower().endswith(_FONT_EXTS)
                and not n.startswith("__MACOSX/")
                and not Path(n).name.startswith(".")
            ]
            if not names:
                return None
            # 굵기가 여러 개면 기본 굵기를 골라야 하는데 파일명 규칙이
            # 제각각이라, ttf 를 먼저 두고 그 다음 이름이 짧은 것을 고른다 —
            # 보통 파생 굵기일수록 이름이 길다 (NanumBrush.ttf vs
            # NanumBrushBold.ttf).
            pick = min(names, key=lambda n: (
                0 if n.lower().endswith(".ttf") else 1, len(Path(n).name), n))
            out = _ZIP_FONT_CACHE / (stem + Path(pick).suffix.lower())
            _ZIP_FONT_CACHE.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(out.name + ".part")
            with z.open(pick) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
            tmp.replace(out)
            return out
    except Exception:
        return None


def _resolve_font_file(font_id: int, allow_zip: bool = True) -> Path | None:
    """allow_zip=False 면 ZIP 폴백을 타지 않는다.

    UI 폰트(_UI_FONT_ID)는 서브셋 없이 통째로 읽는 경로라, ZIP 안의 큰 CJK
    원본이 걸리면 메모리를 그대로 뒤집어쓴다. UI 폰트는 항상 번들되어 있으니
    폴백이 필요 없고, 없으면 있던 대로 PIL 기본 폰트로 떨어지면 된다.
    """
    resolved = FONT_RESOLUTION.get(font_id)
    if resolved and Path(resolved[0]).exists():
        return Path(resolved[0])
    p = font_path(font_id)
    if p.exists():
        return p
    bp = bundled_font_path(font_id)
    if bp.exists():
        return bp
    return _font_from_zip(font_id) if allow_zip else None


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

    ui_font_file = _resolve_font_file(_UI_FONT_ID, allow_zip=False)
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
            # 서브셋 파싱은 성공해도 실제 래스터라이즈 단계에서 FreeType이
            # 실패하는 폰트가 실제로 있었다("Bitmap missing for glyph" —
            # id=223, 손상된 힌팅 바이트코드로 추정). 본 렌더링 전에 미리
            # 한 번 그려서 검증해두면, og-warm이 그 폰트 하나에 걸려
            # remaining이 0이 되지 않고 끝없이 재시도하는 일을 막을 수 있다.
            name_font_bytes.seek(0)
            canary = ImageFont.truetype(name_font_bytes, 64)
            ImageDraw.Draw(Image.new("RGB", (4, 4))).text((0, 0), font_name_text, font=canary, fill=(0, 0, 0))
            name_font_bytes.seek(0)
        except Exception:
            name_font_bytes = None

    square_size = min(W, H)
    target_w = square_size * 0.9

    def _fit_and_render(own_font_bytes):
        """이진 탐색으로 폭에 맞는 크기를 찾고 실제로 렌더링까지 해 본다.

        own_font_bytes가 None이면 처음부터 UI 폰트로만 계산한다.
        """
        def load(size):
            if own_font_bytes is not None:
                own_font_bytes.seek(0)
                return ImageFont.truetype(own_font_bytes, size)
            return _ui_font(size, ui_bold_bytes)

        def measure(size):
            f = load(int(size))
            bbox = d.textbbox((0, 0), font_name_text, font=f)
            return bbox[2] - bbox[0]

        lo, hi = 10, 300
        for _ in range(24):
            mid = (lo + hi) / 2
            if measure(mid) < target_w:
                lo = mid
            else:
                hi = mid
        size = max(int(lo), 10)
        f = load(size)
        bbox = d.textbbox((0, 0), font_name_text, font=f)
        return f, bbox, size

    try:
        name_font, name_bbox, name_size = _fit_and_render(name_font_bytes)
    except Exception:
        # 폰트 파일 자체는 열리지만(_subset_font_to_fontobject 성공) 특정
        # 글자에서 FreeType 렌더링 단계가 실패하는 폰트가 실제로 있었다
        # (예: "Bitmap missing for glyph" — id=223). 이 경우를 못 잡으면
        # og-warm 이 이 폰트 하나에 걸려 remaining 이 0이 되지 않고
        # 끝없이 반복된다. 실제 폰트 대신 UI 폰트로 폴백해 카드 생성을
        # 계속 진행한다 — 그 폰트 자체가 깨졌다는 신호이니 반쯤 깨진
        # 카드보다 완성된 카드가 낫다.
        name_font, name_bbox, name_size = _fit_and_render(None)
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

    # by 는 "블록의 잉크 윗선"이고 center_text 의 y 는 "그리기 원점"이라 서로
    # 다르다. 그 차이가 글자 윗여백(top bearing = bbox[1])인데, 이름이 짧아
    # 크게 조판될수록 이 값이 커진다. 예전에는 이걸 빼지 않아 배포처 줄이
    # 폰트명 아래로 파고들었다 (세 글자짜리 이름에서 특히 심했다 — 산하엽).
    name_y = by - name_bbox[1]

    # 폰트명 (실제 폰트로 렌더링)
    try:
        center_text(name_y, font_name_text, name_font, TEXT_COLOR)
    except Exception:
        # 크기 탐색 단계(_fit_and_render)는 통과했지만 최종 크기에서만
        # 그리기가 실패하는 경우까지 대비한 마지막 안전망.
        center_text(name_y, font_name_text, _ui_font(name_size, ui_bold_bytes), TEXT_COLOR)

    # 배포처 — 폰트명 잉크 아랫선에서 gap2 만큼 띄운 자리가 잉크 윗선이 되게
    sub_y = by + name_h + gap2 - sub_bbox[1]
    center_text(sub_y, sub_text, sub_font, MUTED)

    # 하단 로고 마크 (사이트 좌상단 로고와 동일 스타일)
    center_logo_mark(H - pad - 62)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _font_covers(path: Path, text: str) -> bool:
    """폰트가 text의 모든 글자를 갖고 있는지 cmap으로 확인.

    허브 제목을 추천 1순위 폰트로 렌더링하는데, 그 폰트에 없는 글자가 하나라도
    있으면 두부(.notdef)가 찍힌다. 한글 폰트에 가운뎃점(·)이 없는 경우가 흔하고
    ('인스타 · 카드뉴스'), 영문 전용 폰트는 한글이 통째로 없다. 미리 확인해서
    하나라도 빠지면 UI 폰트로 통째 폴백한다 — 반쯤 깨진 이미지보다 낫다.
    """
    from fontTools.ttLib import TTFont

    try:
        tt = TTFont(str(path), fontNumber=0, lazy=True)
        try:
            cmap = tt.getBestCmap()
        finally:
            tt.close()
    except Exception:
        return False
    return all(ord(ch) in cmap for ch in text if not ch.isspace())


def _generate_hub(title: str, subtitle: str, total: int, lead_font_id: int | None) -> bytes:
    """용도 허브 og:image.

    폰트 카드(_generate)와 같은 배경·카드·로고마크를 쓰되, 허브임을 알 수 있게
    윗줄 라벨과 종수 배지를 둔다. 제목은 그 허브의 추천 1순위 폰트로 렌더링한다 —
    허브 10개가 서로 다른 서체로 보여서 타임라인에서 구분되고, 폰트 사이트답게
    이미지 자체가 그 폰트의 견본이 된다.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    pad = 60
    d.rounded_rectangle([pad, pad, W - pad, H - pad], radius=28,
                        fill=CARD_BG, outline=BORDER, width=2)

    ui_bytes = None
    ui_file = _resolve_font_file(_UI_FONT_ID, allow_zip=False)
    if ui_file:
        try:
            ui_bytes = _woff2_to_fontobject(ui_file)
        except Exception:
            ui_bytes = None

    def ui_font(size):
        if ui_bytes is not None:
            ui_bytes.seek(0)
            try:
                return ImageFont.truetype(ui_bytes, size)
            except Exception:
                pass
        return ImageFont.load_default()

    # 제목용 폰트 — 커버리지가 확인된 경우에만 추천 1순위 폰트를 쓴다
    title_bytes = None
    if lead_font_id:
        lead_file = _resolve_font_file(lead_font_id)
        if lead_file and _font_covers(lead_file, title):
            try:
                title_bytes = _subset_font_to_fontobject(lead_file, title)
            except Exception:
                title_bytes = None

    def title_font(size):
        if title_bytes is not None:
            title_bytes.seek(0)
            try:
                return ImageFont.truetype(title_bytes, int(size))
            except Exception:
                pass
        return ui_font(int(size))

    cx = W // 2

    def center(y, text, font, fill):
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        d.text((cx - (r - l) / 2 - l, y - t), text, font=font, fill=fill)
        return b - t

    def height(text, font):
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        return b - t

    def fit(text, target_w, make_font, hi=150):
        """target_w 안에 들어가는 최대 글자 크기를 이분탐색으로 찾는다."""
        lo = 10
        for _ in range(22):
            mid = (lo + hi) / 2
            l, _t, r, _b = d.textbbox((0, 0), text, font=make_font(mid))
            if (r - l) < target_w:
                lo = mid
            else:
                hi = mid
        return make_font(max(int(lo), 10))

    # 제목은 정사각형(630x630) 크롭을 기준으로 맞춘다. 카드 폭(1080)에 맞추면
    # 카카오톡처럼 가운데를 정사각형으로 잘라 쓰는 곳에서 '인스타 · 카드뉴스'의
    # 양끝이 잘려 나간다 — 폰트 카드가 같은 이유로 쓰는 기준(_generate)이다.
    square_w = min(W, H) * 0.9
    tfont = fit(title, square_w, title_font)

    f_eyebrow = ui_font(28)
    f_badge = ui_font(26)
    # 부제는 30px 고정이되, 카드를 넘칠 만큼 길면 줄인다 (어드민에서 길게 쓸 수 있다)
    f_sub = ui_font(30)
    if subtitle:
        l, _t, r, _b = d.textbbox((0, 0), subtitle, font=f_sub)
        if (r - l) > (W - pad * 2) * 0.86:
            f_sub = fit(subtitle, (W - pad * 2) * 0.86, ui_font, hi=30)

    eyebrow = "무료 한글 폰트 추천"
    badge = f"{total}종 · 상업적 이용 가능"

    GAP1, GAP2, GAP3 = 34, 40, 34
    badge_pad_y = 14
    badge_h = height(badge, f_badge) + badge_pad_y * 2

    block = (height(eyebrow, f_eyebrow) + GAP1 + height(title, tfont)
             + GAP2 + height(subtitle, f_sub) + GAP3 + badge_h)

    # 하단 로고마크 자리를 뺀 카드 안쪽에서 수직 가운데
    watermark_reserved = 90
    y = pad + ((H - pad - watermark_reserved) - pad - block) / 2

    y += center(y, eyebrow, f_eyebrow, ACCENT) + GAP1
    y += center(y, title, tfont, TEXT_COLOR) + GAP2
    y += center(y, subtitle, f_sub, MUTED) + GAP3

    l, t, r, b = d.textbbox((0, 0), badge, font=f_badge)
    bw = r - l
    x0 = cx - (bw + 52) / 2
    d.rounded_rectangle([x0, y, x0 + bw + 52, y + badge_h],
                        radius=badge_h / 2, fill=ACCENT)
    d.text((x0 + 26 - l, y + badge_pad_y - t), badge, font=f_badge, fill="#FFFFFF")

    # 하단 로고 마크 — 폰트 카드와 동일 (사이트 좌상단 로고 스타일)
    logo_size = 32
    lf = ui_font(logo_size)
    l, t, r, b = d.textbbox((0, 0), "폰트픽", font=lf)
    tw, th = r - l, b - t
    dot = round(logo_size * 0.35)
    gap = round(logo_size * 0.28)
    ly = H - pad - 62
    sx = cx - (tw + gap + dot) / 2
    d.text((sx - l, ly), "폰트픽", font=lf, fill=TEXT_COLOR)
    dx = sx + tw + gap
    dy = ly + th - dot - round(logo_size * 0.06)
    d.rounded_rectangle([dx, dy, dx + dot, dy + dot], radius=2, fill=ACCENT)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _hub_cache_key(slug: str, title: str, subtitle: str, total: int,
                   lead_font_id: int | None) -> str:
    """허브 캐시 키 — 그림에 들어가는 값이 하나라도 바뀌면 키가 바뀐다.

    어드민에서 제목·문구를 고치거나 폰트가 늘어 종수가 변하면 새로 만들어야 한다.
    1순위 폰트 파일이 교체되는 경우도 있어 mtime까지 포함한다.
    """
    import hashlib

    mtime = 0
    if lead_font_id:
        p = _resolve_font_file(lead_font_id)
        if p:
            mtime = int(p.stat().st_mtime)
    sig = f"{title}|{subtitle}|{total}|{lead_font_id}|{mtime}"
    h = hashlib.md5(sig.encode("utf-8")).hexdigest()[:10]
    return f"hub-{slug}-v{_HUB_CACHE_VERSION}-{h}.png"


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


@hub_router.get("/{slug}/og-image.png")
def get_hub_og_image(slug: str, db: Session = Depends(get_db)):
    """용도 허브 og:image — /use/{slug}를 공유했을 때 뜨는 카드."""
    from fastapi.responses import Response
    from ..models import UseCase
    from .use_case_route import PICK_CARD_LIMIT, hub_font_total

    uc = db.query(UseCase).filter(UseCase.slug == slug).first()
    if uc is None or not uc.is_active:
        raise HTTPException(status_code=404, detail="허브를 찾을 수 없습니다")

    picks = [f for f in uc.fonts if f.font is not None][:PICK_CARD_LIMIT]
    lead_font_id = picks[0].font_id if picks else None
    total = hub_font_total(db, uc)

    cache_path = CACHE_DIR / _hub_cache_key(
        slug, uc.title, uc.subtitle or "", total, lead_font_id
    )
    headers = {"Cache-Control": "public, max-age=86400"}
    if cache_path.exists():
        return FileResponse(cache_path, media_type="image/png", headers=headers)

    # 폰트 카드와 같은 락을 공유한다 — 메모리 스파이크를 막는 게 목적이라
    # 종류별로 락을 나누면 동시에 두 건이 돌아 의미가 없어진다.
    try:
        with _GEN_LOCK:
            if cache_path.exists():
                return FileResponse(cache_path, media_type="image/png", headers=headers)
            try:
                data = _generate_hub(uc.title, uc.subtitle or "", total, lead_font_id)
                try:
                    cache_path.write_bytes(data)
                except Exception:
                    return Response(content=data, media_type="image/png", headers=headers)
            finally:
                gc.collect()
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"이미지 생성 실패: {e}")

    return FileResponse(cache_path, media_type="image/png", headers=headers)


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
