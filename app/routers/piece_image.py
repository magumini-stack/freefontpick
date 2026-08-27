"""폰트 조각 이미지 생성  GET /api/fonts/{id}/piece.png?text=곧&size=1500&color=fff

홍보물에서 "그 서체로만 조판돼야 하는 글자"를 배경 없는 PNG로 내려준다.

왜 필요한가
  캔바·미리캔버스 같은 편집 도구에는 폰트픽 서체가 없다. 그래서 폰트 소개
  포스터를 그런 도구에서 만들면 정작 주인공인 서체가 다른 글꼴로 나온다.
  글자를 이미지로 내려주면 편집 도구는 배경·색보정만 맡고, 서체가 드러나야
  하는 부분은 실제 폰트 파일로 렌더링된 것을 그대로 쓸 수 있다.

  og-image.png 와 하는 일은 같지만, 그쪽은 폰트명·배포처가 박힌 완성된 카드라
  다른 문구를 넣을 수 없다. 이 엔드포인트는 글자·크기·색·굵기를 받는다.

og_image.py 에서 가져다 쓰는 것
  - 서브셋 렌더링: CJK 폰트를 통째로 파싱하면 컨테이너가 죽는다(502). 실제로
    그릴 글자만 추려낸다.
  - 생성 직렬화 락: 순간 메모리가 크게 튀므로 항상 한 번에 하나만 만든다.
  - 디스크 캐시: 파일 mtime을 키에 넣어 폰트가 교체되면 자동 무효화된다.

⚠ 키를 요구하는 이유
  webfont.css 와 같다. 폰트픽에는 재배포 금지 라이선스 폰트가 있고, 이걸
  무조건 열면 누구나 폰트픽을 글자 이미지 API로 쓸 수 있게 된다.
  WEBFONT_CSS_KEY 를 그대로 쓴다 — 홍보물 제작이라는 용도가 같으므로 키를
  따로 두면 관리만 늘어난다.
"""
import gc
import os
import re
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Font
from .files import WEBFONT_CSS_KEY, _pick_font_file
from .og_image import _subset_font_to_fontobject

router = APIRouter(prefix="/api/fonts", tags=["piece-image"])

CACHE_DIR = Path(os.getenv("PIECEIMAGE_CACHE_DIR", "/app/user_data/piece_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 렌더링 로직이 바뀌면 올려서 기존 캐시를 무효화한다.
_CACHE_VERSION = 1

# 한도. 이 엔드포인트는 글자 수 × 크기가 그대로 이미지 넓이가 되므로,
# 막아 두지 않으면 요청 하나로 수백 MB를 잡을 수 있다.
MAX_TEXT = 40           # 홍보물 한 덩어리면 충분하다. 문단을 넣을 곳이 아니다.
MAX_SIZE = 2000         # 대표 글자 한 자를 1500px로 쓰는 것이 지금 최대 용례다.
MAX_PIXELS = 8_000_000  # 약 4000×2000. RGBA로 32MB 남짓.

# 캐시는 글자·크기·색 조합마다 파일이 생겨 폰트 수만큼으로 한정되지 않는다.
# 그래서 파일 수 상한을 두고 넘치면 오래된 것부터 버린다.
MAX_CACHE_FILES = 2000

_HEADERS = {
    # 로컬 파일(file://)에서 열면 Origin이 "null"이라 화이트리스트가 통하지 않는다.
    # webfont.css 와 같은 이유로 열어 두고, 접근 제어는 키가 담당한다.
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "public, max-age=86400",
}

# 생성 직렬화용 락 — og_image 와 같은 이유(순간 메모리). 캐시 히트는 락을 타지 않는다.
_GEN_LOCK = threading.Lock()

_HEX = re.compile(r"^[0-9a-fA-F]+$")


def _parse_color(value: str) -> tuple:
    """색을 RGBA 튜플로. # 없이 3·6·8자리 16진수를 받는다.

    URL에 넣는 값이라 # 는 인코딩이 번거로워 빼고 받는다.
    8자리는 마지막 두 자리가 투명도다 (fff8 이 아니라 ffffff80 형식).
    """
    v = (value or "").strip().lstrip("#")
    if not v or not _HEX.match(v) or len(v) not in (3, 6, 8):
        raise HTTPException(
            status_code=400,
            detail="color 는 # 없는 16진수 3·6·8자리여야 합니다. 예: fff, 1a1b1d, ffffff80",
        )
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    r, g, b = (int(v[i:i + 2], 16) for i in (0, 2, 4))
    a = int(v[6:8], 16) if len(v) == 8 else 255
    return (r, g, b, a)


def _missing_glyphs(path: Path, text: str) -> list:
    """서체에 없는 글자를 찾는다.

    없는 글자는 두부(.notdef)로 조용히 찍힌다. 이 엔드포인트는 "그 서체로
    보여주는 것"이 목적이라 폴백이 의미가 없으므로, 반쯤 깨진 이미지를
    내려주는 대신 어느 글자가 없는지 알려주고 실패시킨다.
    """
    from fontTools.ttLib import TTFont

    try:
        tt = TTFont(str(path), fontNumber=0, lazy=True)
        try:
            cmap = tt.getBestCmap()
        finally:
            tt.close()
    except Exception:
        return list(dict.fromkeys(ch for ch in text if not ch.isspace()))
    return list(dict.fromkeys(
        ch for ch in text if not ch.isspace() and ord(ch) not in cmap
    ))


def _render(path: Path, text: str, size: int, rgba: tuple) -> bytes:
    """글자를 딱 맞게 잘라 배경이 투명한 PNG 바이트로."""
    from PIL import Image, ImageDraw, ImageFont

    face = ImageFont.truetype(_subset_font_to_fontobject(path, text), size)

    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=face)

    # 획이 자간 밖으로 넘치는 서체가 있어 여유를 둔다. 잘리는 쪽이 더 나쁘다.
    pad = max(4, size // 12)
    width = (right - left) + pad * 2
    height = (bottom - top) + pad * 2

    if width <= 0 or height <= 0:
        raise HTTPException(status_code=422, detail="그릴 것이 없습니다. text 를 확인하세요.")
    if width * height > MAX_PIXELS:
        raise HTTPException(
            status_code=413,
            detail=(f"이미지가 너무 큽니다 ({width}×{height}). "
                    f"size 를 줄이거나 text 를 짧게 하세요."),
        )

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((pad - left, pad - top), text, font=face, fill=rgba)

    import io
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _cache_key(font_id: int, weight: int, text: str, size: int,
               color: str, path: Path) -> str:
    """그림에 들어가는 값이 하나라도 바뀌면 키가 바뀐다.

    text 는 길이·문자 제한이 없는 값이라 파일명에 그대로 쓸 수 없다(경로 문자,
    길이 제한). 통째로 해시한다.
    """
    import hashlib

    mtime = int(path.stat().st_mtime) if path.exists() else 0
    sig = f"{font_id}|{weight}|{text}|{size}|{color}|{mtime}"
    h = hashlib.md5(sig.encode("utf-8")).hexdigest()[:16]
    return f"piece-{font_id:03d}-v{_CACHE_VERSION}-{h}.png"


def _prune_cache() -> None:
    """캐시 파일 수가 상한을 넘으면 오래된 것부터 버린다.

    og_cache 와 달리 여기는 문구 조합마다 파일이 생겨 상한 없이 늘어난다.
    지우다 실패해도 생성 자체는 성공한 것이므로 조용히 넘어간다.
    """
    try:
        files = sorted(CACHE_DIR.glob("piece-*.png"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    if len(files) <= MAX_CACHE_FILES:
        return
    for p in files[:len(files) - MAX_CACHE_FILES + MAX_CACHE_FILES // 10]:
        try:
            p.unlink()
        except OSError:
            pass


@router.get("/{font_id}/piece.png")
def get_piece_image(
    font_id: int,
    text: str = Query(..., description="그릴 글자"),
    size: int = Query(400, ge=16, le=MAX_SIZE, description="글자 크기(px)"),
    color: str = Query("000", description="# 없는 16진수 3·6·8자리"),
    weight: int = Query(0, ge=0, le=1000, description="굵기. 0이면 대표 파일"),
    key: str = Query("", description="발급키"),
    db: Session = Depends(get_db),
):
    """폰트 조각 PNG.

        <img src="https://freefontpick.co.kr/api/fonts/1/piece.png
                  ?text=곧&size=1500&color=fff&weight=300&key=발급키">

    배경은 투명하고, 글자에 딱 맞게 잘려 나온다. 크기·여백은 받는 쪽에서
    맞추는 것을 전제로 넉넉하게 그린다.

    굵기를 지정하면 그 굵기 파일로 조판한다. 굵기 사다리(UL L R M SB B ...)처럼
    라벨마다 실제 굵기가 달라야 하는 조판은 이 파라미터로만 만들 수 있다 —
    편집 도구에서 굵게 버튼을 누르면 합성 볼드라 가짜 대비가 된다.
    """
    if not WEBFONT_CSS_KEY:
        # 키가 설정되지 않은 서버에서는 기능 자체가 없는 것처럼 둔다.
        raise HTTPException(status_code=404, detail="Not Found")
    if key != WEBFONT_CSS_KEY:
        raise HTTPException(status_code=403, detail="유효하지 않은 키입니다")

    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 가 비어 있습니다")
    if len(text) > MAX_TEXT:
        raise HTTPException(
            status_code=400,
            detail=f"text 는 {MAX_TEXT}자까지입니다. 문단이 아니라 홍보물 한 덩어리를 위한 것입니다.",
        )

    rgba = _parse_color(color)

    font = db.query(Font).filter(Font.id == font_id).first()
    if font is None:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    path, _ = _pick_font_file(font_id, weight)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=(f"{font.name} 은 폰트픽에 파일이 없습니다. "
                    f"외부 CDN 웹폰트로만 등록된 폰트입니다."),
        )

    gone = _missing_glyphs(path, text)
    if gone:
        # 두부가 찍힌 이미지를 내려주면 받는 쪽에서 원인을 못 찾는다.
        raise HTTPException(
            status_code=422,
            detail=f"{font.name} 에 없는 글자입니다: {''.join(gone)}",
        )

    cache_path = CACHE_DIR / _cache_key(font_id, weight, text, size, color, path)
    if cache_path.exists():
        return FileResponse(cache_path, media_type="image/png", headers=_HEADERS)

    with _GEN_LOCK:
        # 락을 기다리는 동안 다른 요청이 같은 그림을 만들었을 수 있다.
        if cache_path.exists():
            return FileResponse(cache_path, media_type="image/png", headers=_HEADERS)
        try:
            data = _render(path, text, size, rgba)
            try:
                cache_path.write_bytes(data)
                _prune_cache()
            except OSError:
                # 디스크에 못 써도 그림은 만들어졌다. 캐시 없이 그대로 내려준다.
                return Response(content=data, media_type="image/png", headers=_HEADERS)
        finally:
            # 폰트 파싱 객체를 즉시 회수한다. 예외로 끝난 경우에도 반드시.
            gc.collect()

    return FileResponse(cache_path, media_type="image/png", headers=_HEADERS)
