"""폰트 파일 업로드(WOFF2 전용) + 다운로드/삭제

⚠️ 2026-07 개정: 서버 측 폰트 변환(서브셋/woff2 변환) 완전 제거.
  - 과거: ttf/otf 업로드 → 서버가 fontTools로 서브셋+woff2 변환
  - 문제: 대용량 폰트 변환 시 메모리 폭주로 앱 전체가 다운되는 사고 발생
  - 현재: 어드민이 이미 woff2로 변환해서 올리므로, 서버는 검증 후 그대로 저장만 한다.
    변환이 없으니 메모리 사용량이 파일 크기 수준으로 고정되어 안전하다.

업로드 시 폰트의 stack 앞에 FFP-{id} family를 자동으로 추가해서
프론트엔드 미리보기에 즉시 적용되도록 한다.

⚠️ 2026-07 추가: 어드민 굵기별 개별 등록 (FontWeight 테이블).
  - 기존에는 굵기 세트를 매니페스트(manifest.json) 일괄 업로드로만 관리했음
    (GitHub Desktop으로 zip push → 이름 매칭). 이번 개정으로 어드민 화면에서
    폰트 하나씩 "대표 굵기" 지정 + "추가 굵기" 파일 업로드가 가능해짐.
  - GET /api/fonts/{id}/weights 는 세 소스를 우선순위대로 병합해서 반환한다:
    1) DB FontWeight (어드민 개별 업로드) — 가장 신뢰도 높음
    2) 매니페스트 기반 WEIGHT_RESOLUTION (기존 대량 업로드 시스템)
    3) 대표 파일(font.has_file) 자체를 font.primary_weight로 노출
    같은 굵기값이 여러 소스에 있으면 우선순위가 높은 쪽이 이긴다.
"""
import os
import traceback
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Font, FontWeight
from ..auth import require_password_changed
from ..schemas import FileUploadResponse, FontWeightOut

router = APIRouter(prefix="/api/fonts", tags=["files"])

# 영구 저장 경로 — 카페24 정책상 /app/user_data/만 보존
FONTS_DIR = Path(os.getenv("FONTS_DIR", "/app/user_data/fonts"))
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# 배포에 묶인 시드 폰트 경로 (읽기 전용 fallback)
BUNDLED_FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "fonts"
# 저장소 루트 /fonts (시드 번들의 실제 위치일 수 있음)
ROOT_FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "fonts"

# 굵기 라벨 기본값 (어드민에서 라벨을 비워두면 이걸로 채움)
WEIGHT_LABELS = {
    100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular",
    500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black",
}

# ─── 폰트 파일 해석 (이름 기반) ───────────────────────────
import json as _json2
import re as _re2

_SEED_JSON = Path(__file__).resolve().parent.parent.parent / "seed_data.json"


def _norm_font_name(s: str) -> str:
    return "".join((s or "").split()).lower()


def _seed_name_map() -> dict:
    try:
        with open(_SEED_JSON, encoding="utf-8") as f:
            data = _json2.load(f)
        return {_norm_font_name(x["name"]): x["id"] for x in data.get("fonts", [])}
    except Exception:
        return {}


def _bundled_candidates(fid: int):
    for d in (BUNDLED_FONTS_DIR, ROOT_FONTS_DIR):
        p = d / f"font-{fid:03d}.woff2"
        if p.exists():
            yield p


def _embedded_names(path: Path) -> list:
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
    if not embedded:
        return True
    dn = _norm_font_name(db_name)
    if len(dn) < 2:
        return True
    for en in embedded:
        if dn in en or en in dn:
            return True
    return False


FONT_RESOLUTION: dict = {}
FONT_AUDIT: list = []

WEIGHT_RESOLUTION: dict = {}
WEIGHT_UNMATCHED: list = []


def _weight_dirs():
    # 저장소(ROOT_FONTS_DIR)가 관리 주체이므로 최우선
    return [ROOT_FONTS_DIR / "weights", FONTS_DIR / "weights", BUNDLED_FONTS_DIR / "weights"]


def _load_weight_manifests() -> dict:
    merged = {}
    for d in _weight_dirs():
        mf = d / "manifest.json"
        if not mf.exists():
            continue
        try:
            with open(mf, encoding="utf-8") as f:
                items = _json2.load(f)
        except Exception as e:
            print(f"[fonts] weights manifest 파싱 실패 {mf}: {e}")
            continue
        for it in items:
            key = _norm_font_name(it.get("name", ""))
            if not key or key in merged:
                continue
            entries = []
            for fe in it.get("files", []):
                p = d / fe.get("file", "")
                if p.exists():
                    entries.append({
                        "weight": int(fe.get("weight", 400)),
                        "label": fe.get("label", str(fe.get("weight", 400))),
                        "path": str(p),
                    })
            if entries:
                entries.sort(key=lambda e: e["weight"])
                merged[key] = entries
    return merged


def build_font_resolution(db) -> dict:
    from ..models import Font as _Font

    seed_map = _seed_name_map()
    weight_map = _load_weight_manifests()
    weight_keys_used = set()
    FONT_RESOLUTION.clear()
    FONT_AUDIT.clear()
    WEIGHT_RESOLUTION.clear()
    WEIGHT_UNMATCHED.clear()
    healed = 0

    for font in db.query(_Font).all():
        entry = {"id": font.id, "name": font.name, "source": "none",
                 "path": None, "note": ""}
        chosen = None

        up = font_path(font.id)
        if up.exists():
            chosen = (up, "user")
            emb = _embedded_names(up)
            if emb and not _name_matches(font.name, emb):
                entry["note"] = f"내장이름 확인 필요: {emb[:3]}"

        wkey = _norm_font_name(font.name)
        weights = weight_map.get(wkey)
        if weights:
            WEIGHT_RESOLUTION[font.id] = weights
            weight_keys_used.add(wkey)
            entry["weights"] = [w["weight"] for w in weights]
            if chosen is None:
                base = min(weights, key=lambda w: abs(w["weight"] - 400))
                chosen = (Path(base["path"]), "weights")

        if chosen is None:
            sid = seed_map.get(_norm_font_name(font.name))
            if sid:
                for p in _bundled_candidates(sid):
                    chosen = (p, "bundled-by-name")
                    break

        if chosen:
            FONT_RESOLUTION[font.id] = (str(chosen[0]), chosen[1])
            entry["source"], entry["path"] = chosen[1], str(chosen[0])

        want_has_file = chosen is not None
        if weights:
            want_weights_label = f"{len(weights)}종"
            if font.weights != want_weights_label:
                font.weights = want_weights_label
                healed += 1
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

    for key in weight_map:
        if key not in weight_keys_used:
            WEIGHT_UNMATCHED.append(key)

    db.commit()
    summary = {
        "total": len(FONT_AUDIT),
        "weight_fonts": len(WEIGHT_RESOLUTION),
        "weight_unmatched": WEIGHT_UNMATCHED,
        "user": sum(1 for e in FONT_AUDIT if e["source"] == "user"),
        "bundled_by_name": sum(1 for e in FONT_AUDIT if e["source"] == "bundled-by-name"),
        "bundled_by_id": sum(1 for e in FONT_AUDIT if e["source"] == "bundled-by-id"),
        "missing": sum(1 for e in FONT_AUDIT if e["source"] == "none"),
        "healed_rows": healed,
        "_debug_marker": "v2-priority-fix-20260712",
    }
    print(f"[fonts] 파일 해석 완료: {summary}")
    return summary


MAX_UPLOAD_SIZE = 5 * 1024 * 1024
WOFF2_MAGIC = b"wOF2"


def font_path(font_id: int) -> Path:
    return FONTS_DIR / f"font-{font_id:03d}.woff2"


def bundled_font_path(font_id: int) -> Path:
    return BUNDLED_FONTS_DIR / f"font-{font_id:03d}.woff2"


def weight_file_path(font_id: int, weight: int) -> Path:
    """어드민이 개별 등록한 굵기 파일 경로."""
    return FONTS_DIR / f"font-{font_id:03d}-w{weight}.woff2"


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


def _validate_woff2(content: bytes):
    """woff2 업로드 공통 검증. 실패 시 HTTPException 발생."""
    if not content:
        raise HTTPException(status_code=400, detail="파일이 비어 있어요")
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_SIZE // 1024 // 1024}MB). "
                   f"웹용 woff2는 보통 1~2MB 이내가 적정합니다. "
                   f"서브셋(글립 수 축소)으로 용량을 줄여서 올려주세요.",
        )
    if content[:4] != WOFF2_MAGIC:
        raise HTTPException(
            status_code=400,
            detail="올바른 WOFF2 파일이 아닙니다. "
                   "확장자만 .woff2로 바꾼 파일은 사용할 수 없어요. "
                   "실제 woff2 형식으로 변환한 파일을 올려주세요.",
        )


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

    filename = (file.filename or "").lower()
    if not filename.endswith(".woff2"):
        raise HTTPException(
            status_code=400,
            detail="WOFF2 파일만 업로드할 수 있습니다. "
                   "ttf/otf 폰트는 먼저 woff2로 변환한 뒤 올려주세요. "
                   "(변환 도구 예: cloudconvert.com, fonttools 등)",
        )

    try:
        content = await file.read()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"파일을 읽을 수 없어요: {e}")

    _validate_woff2(content)

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

    try:
        font.has_file = True
        font.stack = _ensure_stack_has_family(font.stack or "", font_id)
        db.commit()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"파일은 저장됐지만 DB 업데이트 실패: {e}",
        )

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


def _merged_weights(font: Font) -> list:
    """DB FontWeight + 매니페스트 WEIGHT_RESOLUTION + 대표 파일을 우선순위대로 병합.

    우선순위: DB(FontWeight, 어드민 개별 등록) > 매니페스트(대량 업로드) > 대표 파일 1건.
    같은 weight 값은 한 번만 노출한다.

    ⚠️ 대표 파일(3순위) 추가 조건: 매니페스트(2순위)가 이미 이 폰트의 굵기 세트를
    갖고 있으면 대표 파일은 그 세트 중 하나를 그대로 재사용해 만들어진 것일 수 있어
    (예: 400에 가장 가까운 굵기 파일을 대표로 승격) 별도 항목으로 또 추가하면
    실제로는 같은 굵기인데 두 줄로 겹쳐 보이는 문제가 생긴다. 그래서 매니페스트가
    비어있는 폰트(어드민이 "추가 굵기 등록"만 쓰고 매니페스트는 없는 경우 등)에서만
    대표 파일을 별도 항목으로 추가한다.
    """
    out: dict = {}

    # 1순위: 어드민이 개별 등록한 굵기 (DB)
    for fw in sorted(font.extra_weights, key=lambda w: w.weight):
        p = weight_file_path(font.id, fw.weight)
        if p.exists():
            out[fw.weight] = {
                "weight": fw.weight,
                "label": fw.label or WEIGHT_LABELS.get(fw.weight, str(fw.weight)),
                "source": "extra",
                "has_file": True,
                "path": str(p),
            }

    # 2순위: 기존 매니페스트 기반 대량 업로드 시스템
    legacy = WEIGHT_RESOLUTION.get(font.id, [])
    for w in legacy:
        if w["weight"] not in out:
            out[w["weight"]] = {
                "weight": w["weight"],
                "label": w.get("label") or WEIGHT_LABELS.get(w["weight"], str(w["weight"])),
                "source": "legacy",
                "has_file": True,
                "path": w["path"],
            }

    # 3순위: 대표 파일 (primary_weight) — 매니페스트가 없는 폰트에서만 별도 추가
    if not legacy and font.has_file and font.primary_weight and font.primary_weight not in out:
        p = font_path(font.id)
        if p.exists():
            out[font.primary_weight] = {
                "weight": font.primary_weight,
                "label": WEIGHT_LABELS.get(font.primary_weight, str(font.primary_weight)),
                "source": "primary",
                "has_file": True,
                "path": str(p),
            }

    return sorted(out.values(), key=lambda w: w["weight"])


@router.get("/{font_id}/weights", response_model=List[FontWeightOut])
def font_weights(font_id: int, db: Session = Depends(get_db)):
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        return []
    return _merged_weights(font)


@router.post("/{font_id}/weights", response_model=FontWeightOut, status_code=status.HTTP_201_CREATED)
async def add_font_weight(
    font_id: int,
    weight: int = Form(...),
    label: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    """어드민이 폰트에 굵기 하나를 개별 등록 (파일 업로드 포함).

    이미 같은 굵기가 등록돼 있으면 파일/라벨을 덮어쓴다 (재업로드 = 교체).
    """
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")
    if weight < 100 or weight > 900:
        raise HTTPException(status_code=400, detail="굵기는 100~900 사이 값이어야 합니다")

    filename = (file.filename or "").lower()
    if not filename.endswith(".woff2"):
        raise HTTPException(
            status_code=400,
            detail="WOFF2 파일만 업로드할 수 있습니다. ttf/otf는 먼저 woff2로 변환해주세요.",
        )

    try:
        content = await file.read()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"파일을 읽을 수 없어요: {e}")

    _validate_woff2(content)

    out_path = weight_file_path(font_id, weight)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(content)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"파일 저장 실패 (디스크 권한 문제일 수 있어요): {type(e).__name__}: {e}",
        )

    row = db.query(FontWeight).filter(
        FontWeight.font_id == font_id, FontWeight.weight == weight,
    ).first()
    final_label = label.strip() or WEIGHT_LABELS.get(weight, str(weight))
    if row:
        row.label = final_label
    else:
        row = FontWeight(font_id=font_id, weight=weight, label=final_label)
        db.add(row)

    # 종수 라벨(weights 컬럼) 자가 갱신
    db.commit()
    db.refresh(font)
    font.weights = f"{len(_merged_weights(font))}종"
    db.commit()

    return FontWeightOut(weight=weight, label=final_label, source="extra", has_file=True)


@router.delete("/{font_id}/weights/{weight}", status_code=status.HTTP_204_NO_CONTENT)
def delete_font_weight(
    font_id: int,
    weight: int,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")
    row = db.query(FontWeight).filter(
        FontWeight.font_id == font_id, FontWeight.weight == weight,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="등록된 굵기가 아닙니다")
    p = weight_file_path(font_id, weight)
    if p.exists():
        p.unlink()
    db.delete(row)
    db.commit()
    db.refresh(font)
    font.weights = f"{len(_merged_weights(font))}종"
    db.commit()


@router.get("/{font_id}/file")
def download_font_file(font_id: int, weight: int = 0, db: Session = Depends(get_db)):
    _headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Access-Control-Allow-Origin": "*",
    }
    if weight:
        # 1순위: 어드민이 개별 등록한 굵기 파일
        wp = weight_file_path(font_id, weight)
        if wp.exists():
            return FileResponse(path=wp, media_type="font/woff2", headers=_headers)
        # 2순위: 매니페스트 기반 굵기 파일
        for w in WEIGHT_RESOLUTION.get(font_id, []):
            if w["weight"] == weight and Path(w["path"]).exists():
                return FileResponse(path=w["path"], media_type="font/woff2", headers=_headers)
    resolved = FONT_RESOLUTION.get(font_id)
    if resolved and Path(resolved[0]).exists():
        return FileResponse(path=resolved[0], media_type="font/woff2", headers=_headers)
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
