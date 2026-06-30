"""폰트 파일 업로드 + 자동 서브셋 변환 + 다운로드/삭제

업로드 시 폰트의 stack 앞에 FFP-{id} family를 자동으로 추가해서
프론트엔드 미리보기에 즉시 적용되도록 한다.

폰트 변환은 3단계 fallback:
  1. 서브셋 변환 (한글/영문 글리프만 추출, 크기 축소)
  2. 서브셋 실패 시: 원본을 그대로 woff2로 단순 변환
  3. 둘 다 실패 시: 원본 파일을 그대로 저장 (확장자만 woff2로)

이렇게 하면 변환 단계에서 죽는 폰트도 어쨌든 미리보기에 사용 가능.
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
from ..subset import subset_font_bytes, convert_to_woff2_no_subset

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
    family = _ffp_family(font_id)
    quoted = f"'{family}'"
    if not stack:
        return f"{quoted},'Nanum Gothic',sans-serif"
    if family in stack:
        return stack
    return f"{quoted},{stack}"


def _process_font_bytes(content: bytes, is_english: bool, filename: str) -> tuple[bytes, dict, str]:
    """폰트 파일 바이트를 처리. 3단계 fallback.

    Returns: (final_bytes, info, used_method)
    """
    original_size = len(content)
    # 1단계: 서브셋 변환 시도
    try:
        woff2_bytes, info = subset_font_bytes(content, is_english=is_english)
        info["method"] = "subset"
        return woff2_bytes, info, "subset"
    except Exception as e:
        print(f"[font upload] 서브셋 실패, fallback으로 진행: {e}")
        traceback.print_exc()

    # 2단계: 서브셋 없이 woff2 변환만 시도
    try:
        woff2_bytes = convert_to_woff2_no_subset(content)
        info = {
            "original_size": original_size,
            "output_size": len(woff2_bytes),
            "ratio": round(len(woff2_bytes) / original_size, 4) if original_size else 0,
            "format": "woff2",
            "method": "convert_only",
        }
        print(f"[font upload] convert_only로 처리: {len(woff2_bytes)} bytes")
        return woff2_bytes, info, "convert_only"
    except Exception as e:
        print(f"[font upload] woff2 변환도 실패, 원본 저장으로 진행: {e}")
        traceback.print_exc()

    # 3단계: 변환 자체 실패 → 원본 파일을 그대로 저장
    # (브라우저가 ttf/otf도 @font-face로 로드 가능하니 작동은 함)
    info = {
        "original_size": original_size,
        "output_size": original_size,
        "ratio": 1.0,
        "format": "original",
        "method": "raw",
        "original_filename": filename,
    }
    print(f"[font upload] raw 모드로 원본 저장: {original_size} bytes")
    return content, info, "raw"


@router.post("/{font_id}/file", response_model=FileUploadResponse)
async def upload_font_file(
    font_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    """폰트 파일 업로드.

    어떤 단계에서 실패해도 500이 아닌 명확한 400/413 + 메시지로 응답.
    서브셋 변환 실패해도 원본을 그대로 저장하여 미리보기는 동작하게 함.
    """
    # 1. 폰트 존재 확인
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    # 2. 파일명/확장자 검증
    filename = (file.filename or "").lower()
    if not filename.endswith((".ttf", ".otf", ".woff", ".woff2")):
        raise HTTPException(
            status_code=400,
            detail="지원하지 않는 파일 형식입니다 (ttf, otf, woff, woff2만 가능)",
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
            detail=f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_SIZE // 1024 // 1024}MB)",
        )

    # 4. 폰트 처리 (3단계 fallback)
    try:
        final_bytes, info, method = _process_font_bytes(
            content, bool(font.is_english), filename
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=400,
            detail=f"폰트 처리 중 오류: {type(e).__name__}: {e}",
        )

    # 5. 파일 저장 (이 단계가 실패해도 안전하게)
    out_path = font_path(font_id)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(final_bytes)
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

    msg = f"업로드 완료 ({method}: {info['original_size']//1024}KB → {info['output_size']//1024}KB)"
    return FileUploadResponse(
        id=font.id,
        file_size=info["output_size"],
        original_size=info["original_size"],
        ratio=info["ratio"],
        format=info["format"],
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
