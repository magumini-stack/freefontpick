"""폰트 파일 업로드(WOFF2 전용) + 다운로드/삭제

⚠️ 2026-07 개정: 서버 측 폰트 변환(서브셋/woff2 변환) 완전 제거.
  - 과거: ttf/otf 업로드 → 서버가 fontTools로 서브셋+woff2 변환
  - 문제: 대용량 폰트 변환 시 메모리 폭주로 앱 전체가 다운되는 사고 발생
  - 현재: 어드민이 이미 woff2로 변환해서 올리므로, 서버는 검증 후 그대로 저장만 한다.
    변환이 없으니 메모리 사용량이 파일 크기 수준으로 고정되어 안전하다.

업로드 시 폰트의 stack 앞에 FFP-{id} family를 자동으로 추가해서
프론트엔드 미리보기에 즉시 적용되도록 한다.
"""
import os
import traceback
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Font
from ..auth import require_password_changed
from ..schemas import FileUploadResponse

router = APIRouter(prefix="/api/fonts", tags=["files"])

# 영구 저장 경로 — 카페24 정책상 /app/user_data/만 보존
FONTS_DIR = Path(os.getenv("FONTS_DIR", "/app/user_data/fonts"))
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# 배포에 묶인 시드 폰트 경로 (읽기 전용 fallback)
BUNDLED_FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "fonts"

# 업로드 최대 크기 — 웹 서빙용 woff2는 이 이하가 정상 범위
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

# WOFF2 파일 시그니처 (magic bytes): 'wOF2'
WOFF2_MAGIC = b"wOF2"


def font_path(font_id: int) -> Path:
    return FONTS_DIR / f"font-{font_id:03d}.woff2"


def bundled_font_path(font_id: int) -> Path:
    return BUNDLED_FONTS_DIR / f"font-{font_id:03d}.woff2"


def _ffp_family(font_id: int) -> str:
    return f"FFP-{font_id:03d}"


def _ensure_stack_has_family(stack: str, font_id: int) -> str:
    family = _ffp_family(font_id)
    quoted = f"'{family}'"
    if not stack:
        return f"{quoted},'Nanum Gothic',sans-serif"
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
    """폰트 파일 업로드 — WOFF2 전용.

    서버는 변환을 일절 하지 않는다. 확장자 + magic bytes + 크기만 검증하고
    파일을 그대로 저장한다. (변환 중 OOM으로 앱이 다운되는 사고 재발 방지)
    """
    # 1. 폰트 존재 확인
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    # 2. 확장자 검증 — woff2만 허용
    filename = (file.filename or "").lower()
    if not filename.endswith(".woff2"):
        raise HTTPException(
            status_code=400,
            detail="WOFF2 파일만 업로드할 수 있습니다. "
                   "ttf/otf 폰트는 먼저 woff2로 변환한 뒤 올려주세요. "
                   "(변환 도구 예: cloudconvert.com, fonttools 등)",
        )

    # 3. 본문 읽기 + 크기 제한
    try:
        content = await file.read()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"파일을 읽을 수 없어요: {e}")

    if not content:
        raise HTTPException(status_code=400, detail="파일이 비어 있어요")

    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_SIZE // 1024 // 1024}MB). "
                   f"웹용 woff2는 보통 1~2MB 이내가 적정합니다. "
                   f"서브셋(글립 수 축소)으로 용량을 줄여서 올려주세요.",
        )

    # 4. WOFF2 시그니처 검증 — 확장자만 바꾼 가짜 파일 차단
    if content[:4] != WOFF2_MAGIC:
        raise HTTPException(
            status_code=400,
            detail="올바른 WOFF2 파일이 아닙니다. "
                   "확장자만 .woff2로 바꾼 파일은 사용할 수 없어요. "
                   "실제 woff2 형식으로 변환한 파일을 올려주세요.",
        )

    # 5. 파일 저장 — 변환 없이 그대로
    out_path = font_path(font_id)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(content)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"파일 저장 실패 (디스크 권한 문제일 수 있어요): {type(e).__name__}: {e}",
        )

    # 6. DB 업데이트
    try:
        font.has_file = True
        font.stack = _ensure_stack_has_family(font.stack or "", font_id)
        db.commit()
    except Exception as e:
        traceback.print_exc()
        # 파일은 저장됐는데 DB 업데이트 실패 — 부분 성공 케이스
        raise HTTPException(
            status_code=500,
            detail=f"파일은 저장됐지만 DB 업데이트 실패: {e}",
        )

    size = len(content)
    msg = f"업로드 완료 (woff2 원본 그대로 저장: {size // 1024}KB)"
    return FileUploadResponse(
        id=font.id,
        file_size=size,
        original_size=size,
        ratio=1.0,
        format="woff2",
        message=msg,
    )


@router.get("/{font_id}/file")
def download_font_file(font_id: int):
    """공개 — 폰트 파일 서빙. @font-face로 호출됨.

    우선순위: 사용자 업로드본(/app/user_data/fonts) → 시드 번들(static/fonts)
    """
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
    if not bundled_font_path(font_id).exists():
        font.has_file = False
    db.commit()
