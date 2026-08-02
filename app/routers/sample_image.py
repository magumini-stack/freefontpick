"""폰트 샘플 이미지 — 상세페이지 '글자 견본' 자리를 대체하는 이미지.

이미지가 있으면 상세페이지 ④번 블록이 글자 견본(한글/영문/숫자) 대신
그 이미지를 보여준다. 없으면 지금처럼 글자 견본이 나온다.

DB 컬럼을 두지 않는 이유
------------------------
존재 여부가 곧 파일 존재 여부라서 컬럼을 따로 두면 두 곳이 어긋날 수 있다.
(파일은 지웠는데 컬럼은 남는 식.) 디렉터리를 인덱싱해서 판단하고,
디렉터리 mtime이 바뀔 때만 다시 읽는다 — 매 요청 디스크 스캔은 하지 않는다.

엔드포인트
----------
- GET    /api/fonts/{id}/sample-image   공개. 없으면 404
- POST   /api/fonts/{id}/sample-image   관리자. multipart 업로드 (기존 것 교체)
- DELETE /api/fonts/{id}/sample-image   관리자
"""
import os
import re
import traceback
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Font
from ..auth import require_password_changed

router = APIRouter(prefix="/api/fonts", tags=["sample-image"])

SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", "/app/user_data/samples"))
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

MAX_SAMPLE_SIZE = 3 * 1024 * 1024  # 3MB

# 확장자 → Content-Type. 여기 없는 형식은 받지 않는다.
ALLOWED = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# 매직 넘버 검사 — 확장자만 믿으면 아무 파일이나 .png로 올릴 수 있다.
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_NAME_RE = re.compile(r"^sample-(\d+)\.(jpg|jpeg|png|webp|gif)$", re.I)

# {font_id: 파일명} 캐시와 그때의 디렉터리 mtime
_index: Dict[int, str] = {}
_index_mtime: float = -1.0


def _refresh_index(force: bool = False) -> None:
    global _index, _index_mtime
    try:
        mtime = SAMPLES_DIR.stat().st_mtime
    except FileNotFoundError:
        _index, _index_mtime = {}, -1.0
        return
    if not force and mtime == _index_mtime:
        return
    found: Dict[int, str] = {}
    try:
        for p in SAMPLES_DIR.iterdir():
            m = _NAME_RE.match(p.name)
            if m and p.is_file():
                found[int(m.group(1))] = p.name
    except Exception:
        traceback.print_exc()
        return
    _index, _index_mtime = found, mtime


def has_sample(font_id: int) -> bool:
    """이 폰트에 샘플 이미지가 있는가. fonts 라우터의 직렬화에서 쓴다."""
    _refresh_index()
    return font_id in _index


def sample_path(font_id: int) -> Optional[Path]:
    _refresh_index()
    name = _index.get(font_id)
    return (SAMPLES_DIR / name) if name else None


def _detect_ext(content: bytes, filename: str) -> str:
    """매직 넘버 우선, 안 잡히면 확장자. webp는 RIFF....WEBP 구조."""
    for magic, mime in _MAGIC:
        if content.startswith(magic):
            return {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif"}[mime]
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    ext = Path(filename or "").suffix.lower()
    if ext in ALLOWED:
        return ".jpg" if ext == ".jpeg" else ext
    raise HTTPException(
        status_code=400,
        detail="이미지 파일만 올릴 수 있어요 (JPG, PNG, WEBP, GIF).",
    )


@router.get("/{font_id}/sample-image")
def get_sample_image(font_id: int):
    path = sample_path(font_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="샘플 이미지가 없습니다")
    media = ALLOWED.get(path.suffix.lower(), "application/octet-stream")
    # 이미지는 캐시가 이득이다. 교체하면 파일이 바뀌므로 프론트에서 ?v= 로 무효화한다.
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "public, max-age=86400"})


@router.post("/{font_id}/sample-image")
async def upload_sample_image(
    font_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    try:
        content = await file.read()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"파일을 읽을 수 없어요: {e}")

    if not content:
        raise HTTPException(status_code=400, detail="빈 파일입니다")
    if len(content) > MAX_SAMPLE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"이미지가 너무 큽니다 (최대 {MAX_SAMPLE_SIZE // 1024 // 1024}MB). "
                   "상세페이지에서 바로 보이는 이미지라 용량이 크면 로딩이 느려져요.",
        )

    ext = _detect_ext(content, file.filename or "")

    # 확장자가 바뀔 수 있으므로 기존 파일은 먼저 지운다 (sample-12.png → sample-12.jpg)
    old = sample_path(font_id)
    if old and old.exists():
        try:
            old.unlink()
        except Exception:
            traceback.print_exc()

    out = SAMPLES_DIR / f"sample-{font_id}{ext}"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"이미지 저장 실패 (디스크 권한 문제일 수 있어요): {type(e).__name__}: {e}",
        )

    _refresh_index(force=True)
    return {"font_id": font_id, "filename": out.name, "size": len(content)}


@router.delete("/{font_id}/sample-image", status_code=status.HTTP_204_NO_CONTENT)
def delete_sample_image(
    font_id: int,
    _admin=Depends(require_password_changed),
):
    path = sample_path(font_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="샘플 이미지가 없습니다")
    try:
        path.unlink()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"삭제 실패: {e}")
    _refresh_index(force=True)
    return None
