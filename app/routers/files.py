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
# 저장소 루트 /fonts (시드 번들의 실제 위치일 수 있음)
ROOT_FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "fonts"

# ─── 폰트 파일 해석 (이름 기반) ───────────────────────────
# 문제: 번들 파일 번호(시드 id)와 운영 DB의 폰트 id가 어긋날 수 있음.
#   → id로만 찾으면 '다른 폰트'가 서빙되는 사고 발생.
# 해결: 시작 시 폰트별로 올바른 파일을 이름 기준으로 확정해 캐시.
#   우선순위: 업로드본(신뢰) → 시드이름 매칭 번들
import json as _json2
import re as _re2

_SEED_JSON = Path(__file__).resolve().parent.parent.parent / "seed_data.json"


def _norm_font_name(s: str) -> str:
    return "".join((s or "").split()).lower()


def _seed_name_map() -> dict:
    """정규화된 시드 폰트 이름 → 시드 id"""
    try:
        with open(_SEED_JSON, encoding="utf-8") as f:
            data = _json2.load(f)
        return {_norm_font_name(x["name"]): x["id"] for x in data.get("fonts", [])}
    except Exception:
        return {}


def _bundled_candidates(fid: int):
    """읽기 전용 번들 폴더만 — 업로드 폴더(FONTS_DIR)는 id 체계가 달라 제외"""
    for d in (BUNDLED_FONTS_DIR, ROOT_FONTS_DIR):
        p = d / f"font-{fid:03d}.woff2"
        if p.exists():
            yield p


def _embedded_names(path: Path) -> list:
    """woff2 내장 name 테이블의 이름 문자열들 (fontTools 없으면 빈 리스트)"""
    try:
        from fontTools.ttLib import TTFont
        ft = TTFont(str(path), lazy=True)
        names = set()
        for rec in ft["name"].names:
            if rec.nameID in (1, 4, 16):
                try:
                    names.add(_norm_font_name(rec.toUnicode()))
                except Exception:
                    pass
        ft.close()
        return [n for n in names if n]
    except Exception:
        return []


def _name_matches(db_name: str, embedded: list) -> bool:
    """내장 이름과 DB 이름의 느슨한 일치 (부분 포함 양방향)"""
    if not embedded:
        return True  # 검증 불가 시 통과 (fontTools 미설치 등)
    dn = _norm_font_name(db_name)
    if len(dn) < 2:
        return True
    for en in embedded:
        if dn in en or en in dn:
            return True
    return False


# 폰트 id → (경로 문자열, 소스 라벨). 시작 시 build_font_resolution()이 채움.
FONT_RESOLUTION: dict = {}
FONT_AUDIT: list = []


def build_font_resolution(db) -> dict:
    """모든 폰트의 서빙 파일을 이름 기준으로 확정 + has_file/stack 자가치유.

    반환: 요약 dict (audit용). FONT_RESOLUTION/FONT_AUDIT 갱신.
    """
    from ..models import Font as _Font

    seed_map = _seed_name_map()
    FONT_RESOLUTION.clear()
    FONT_AUDIT.clear()
    healed = 0

    for font in db.query(_Font).all():
        entry = {"id": font.id, "name": font.name, "source": "none",
                 "path": None, "note": ""}
        chosen = None

        # 1) 사용자 업로드본 — 어드민이 폰트별로 직접 올린 파일이므로 신뢰.
        #    내장 이름은 감사(audit) 참고용으로만 기록 (영문 내부명 vs 한글 표시명이라 판정에 못 씀)
        up = font_path(font.id)
        if up.exists():
            chosen = (up, "user")
            emb = _embedded_names(up)
            if emb and not _name_matches(font.name, emb):
                entry["note"] = f"내장이름 확인 필요: {emb[:3]}"

        # 2) 시드 이름 → 시드 id 번들 (번들 파일은 시드 id 체계로 번호가 매겨져 있음)
        if chosen is None:
            sid = seed_map.get(_norm_font_name(font.name))
            if sid:
                for p in _bundled_candidates(sid):
                    chosen = (p, "bundled-by-name")
                    break

        if chosen:
            FONT_RESOLUTION[font.id] = (str(chosen[0]), chosen[1])
            entry["source"], entry["path"] = chosen[1], str(chosen[0])

        # ── 자가치유: has_file / stack 정합화 ──
        want_has_file = chosen is not None
        # stack에서 잘못된 FFP-xxx 토큰 제거 후 올바른 것만 prepend
        raw = font.stack or "'Nanum Gothic',sans-serif"
        cleaned = _re2.sub(r"'?FFP-\d{3}'?\s*,?\s*", "", raw).strip().strip(",").strip()
        if not cleaned:
            cleaned = "'Nanum Gothic',sans-serif"
        new_stack = f"'{_ffp_family(font.id)}',{cleaned}" if want_has_file else cleaned
        if bool(font.has_file) != want_has_file or font.stack != new_stack:
            font.has_file = want_has_file
            font.stack = new_stack
            healed += 1

        FONT_AUDIT.append(entry)

    db.commit()
    summary = {
        "total": len(FONT_AUDIT),
        "user": sum(1 for e in FONT_AUDIT if e["source"] == "user"),
        "bundled_by_name": sum(1 for e in FONT_AUDIT if e["source"] == "bundled-by-name"),
        "bundled_by_id": sum(1 for e in FONT_AUDIT if e["source"] == "bundled-by-id"),
        "missing": sum(1 for e in FONT_AUDIT if e["source"] == "none"),
        "healed_rows": healed,
    }
    print(f"[fonts] 파일 해석 완료: {summary}")
    return summary


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

    # 7. 해석 캐시 갱신 — 새 업로드본이 즉시 서빙되도록
    FONT_RESOLUTION[font_id] = (str(out_path), "user")

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

    우선순위: 시작 시 확정된 해석 캐시 → 업로드본 → 시드 번들
    """
    _headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Access-Control-Allow-Origin": "*",
    }
    # 1) 시작 시 확정된 해석 캐시 (이름 기준으로 확정된 경로)
    resolved = FONT_RESOLUTION.get(font_id)
    if resolved and Path(resolved[0]).exists():
        return FileResponse(path=resolved[0], media_type="font/woff2", headers=_headers)
    # 2) 캐시에 없으면 (부팅 후 새로 업로드된 폰트) 업로드본 직접 서빙
    p = font_path(font_id)
    if p.exists():
        FONT_RESOLUTION[font_id] = (str(p), "user")
        return FileResponse(path=p, media_type="font/woff2", headers=_headers)
    bp = bundled_font_path(font_id)
    if bp.exists():
        return FileResponse(path=bp, media_type="font/woff2", headers=_headers)
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
    FONT_RESOLUTION.pop(font_id, None)
    if not bundled_font_path(font_id).exists():
        font.has_file = False
    db.commit()
