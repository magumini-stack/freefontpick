"""폰트 파일 업로드 + 자동 서브셋 변환 + 다운로드/삭제

업로드 시 폰트의 stack 앞에 FFP-{id} family를 자동으로 추가해서
프론트엔드 미리보기에 즉시 적용되도록 한다.
"""
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import Response, FileResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Font
from ..auth import require_password_changed
from ..schemas import FileUploadResponse
from ..subset import subset_font_bytes

router = APIRouter(prefix="/api/fonts", tags=["files"])

# 영구 저장 경로 — 카페24 정책상 /app/user_data/만 보존
FONTS_DIR = Path(os.getenv("FONTS_DIR", "/app/user_data/fonts"))
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# 배포에 묶인 시드 폰트 경로 (읽기 전용 fallback)
BUNDLED_FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "fonts"

# 업로드 최대 크기
MAX_UPLOAD_SIZE = 20 * 1024 * 1024


def font_path(font_id: int) -> Path:
    return FONTS_DIR / f"font-{font_id:03d}.woff2"


def bundled_font_path(font_id: int) -> Path:
    return BUNDLED_FONTS_DIR / f"font-{font_id:03d}.woff2"


def _ffp_family(font_id: int) -> str:
    return f"FFP-{font_id:03d}"


def _ensure_stack_has_family(stack: str, font_id: int) -> str:
    """폰트의 stack 맨 앞에 FFP-{id} family가 포함되도록 보정."""
    family = _ffp_family(font_id)
    quoted = f"'{family}'"
    if not stack:
        return f"{quoted},'Nanum Gothic',sans-serif"
    # 이미 있으면 그대로
    if family in stack:
        return stack
    return f"{quoted},{stack}"


@router.post("/{font_id}/file", response_model=FileUploadResponse)
async def upload_font_file(
    font_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    # 확장자 검증
    name = (file.filename or "").lower()
    if not name.endswith((".ttf", ".otf", ".woff", ".woff2")):
        raise HTTPException(
            status_code=400,
            detail="지원하지 않는 파일 형식입니다 (ttf, otf, woff, woff2만 가능)",
        )

    # 크기 제한
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_SIZE // 1024 // 1024}MB)",
        )

    # 자동 서브셋 변환
    try:
        woff2_bytes, info = subset_font_bytes(content, is_english=bool(font.is_english))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 파일 저장
    out_path = font_path(font_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(woff2_bytes)

    # 미리보기에 폰트가 적용되도록 stack 자동 갱신
    font.has_file = True
    font.stack = _ensure_stack_has_family(font.stack or "", font_id)
    db.commit()

    return FileUploadResponse(
        id=font.id,
        file_size=info["output_size"],
        original_size=info["original_size"],
        ratio=info["ratio"],
        format=info["format"],
        message=f"서브셋 변환 완료 (원본 {info['original_size'] // 1024}KB → {info['output_size'] // 1024}KB)",
    )


@router.get("/{font_id}/file")
def download_font_file(font_id: int):
    """공개 — 폰트 파일 서빙. @font-face로 호출됨.

    우선순위: 사용자 업로드본(/app/user_data/fonts) → 시드 번들(static/fonts)
    """
    # 사용자 업로드본 우선
    p = font_path(font_id)
    if p.exists():
        return FileResponse(
            path=p,
            media_type="font/woff2",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "Access-Control-Allow-Origin": "*",
            },
        )
    # 시드 번들 fallback
    bp = bundled_font_path(font_id)
    if bp.exists():
        return FileResponse(
            path=bp,
            media_type="font/woff2",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "Access-Control-Allow-Origin": "*",
            },
        )
    raise HTTPException(status_code=404, detail="폰트 파일이 없습니다")


@router.delete("/{font_id}/file", status_code=status.HTTP_204_NO_CONTENT)
def delete_font_file(
    font_id: int,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")
    p = font_path(font_id)
    if p.exists():
        p.unlink()
    # 번들 시드가 있으면 has_file 유지 (시드 폰트는 항상 존재)
    if not bundled_font_path(font_id).exists():
        font.has_file = False
    db.commit()
