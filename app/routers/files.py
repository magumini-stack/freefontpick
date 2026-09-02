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

⚠️ 2026-07 추가: 웹폰트 CDN 소스 (Google Fonts 등).
  - Font.webfont_family/webfont_css_url/webfont_weights가 채워져 있으면
    파일 업로드 없이도 _merged_weights()에 "webfont" 소스로 노출된다.
    실제 폰트 로딩은 프론트엔드가 webfont_css_url을 <link>로 로드하고
    webfont_family를 font-family로 사용하는 방식이라, 이 굵기들은 로컬 파일이 없다.

⚠️ 2026-08 수정: 파일 출처(file_source_of) 노출 + 캐시 정책 분리.
  - "어드민에서 폰트 파일을 올렸는데 페이지가 그 폰트를 안 읽어온다"는 증상의
    원인이 둘이었다.
    (1) 프론트가 webfont_family가 있으면 업로드 파일을 아예 건너뛰었다.
        → file_source_of()로 'user' 여부를 내려줘, 프론트가 업로드 파일을
          웹폰트보다 우선하도록 판단할 수 있게 했다.
    (2) /file 응답이 max-age=31536000, immutable 인데 주소에 버전 키가 없어서
        파일을 교체해도 브라우저·CDN이 1년 내내 옛 바이트를 돌려줬다.
        → 어드민이 올린 파일만 ETag 재검증(max-age=0, must-revalidate)으로 바꿨다.
          번들 폰트는 재배포로만 바뀌므로 immutable 유지.
"""
import os
import traceback
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi import Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Font, FontWeight
from ..redistribution import NO_REDISTRIBUTE
from ..auth import require_password_changed
from ..schemas import FileUploadResponse, FontWeightOut
from ..site import SITE_URL

router = APIRouter(prefix="/api/fonts", tags=["files"])

# 영구 저장 경로 — 카페24 정책상 /app/user_data/만 보존
FONTS_DIR = Path(os.getenv("FONTS_DIR", "/app/user_data/fonts"))
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# ─── 배포용 ZIP ───────────────────────────────────────────
# 어드민이 올린 원본 폰트 묶음(ttf/otf 등). 사용자가 '다운로드'를 눌렀을 때만
# 나간다 — 화면에 글자를 그리는 woff2(FONTS_DIR)와 쓰임이 달라 자리도 나눈다.
#
# /app/user_data/ 아래에 두는 이유는 FONTS_DIR 과 같다 — 카페24는 이 경로만
# 배포 사이에 보존한다. 저장소에 넣으면 폰트를 하나 추가할 때마다 push 해야 한다.
ZIPS_DIR = Path(os.getenv("FONT_ZIPS_DIR", "/app/user_data/fontzips"))
# woff2(5MB)보다 넉넉히 잡는다. ttf/otf 여러 굵기가 한 묶음에 들어온다.
# 30MB 였다. 굵기 5종짜리 한글 폰트 묶음이 이 문턱을 넘는다(스포카 한 산스 37.1MB).
# 서버가 파일을 통째로 메모리에 읽으므로 이 값이 곧 요청 하나가 쓰는 메모리다 —
# 일괄 업로드가 하나씩 차례로 보내는 것도 그래서다.
MAX_ZIP_SIZE = 50 * 1024 * 1024


# 저장소에 함께 배포되는 ZIP (읽기 전용). 폰트 파일이 FONTS_DIR(업로드) 과
# ROOT_FONTS_DIR(저장소) 두 겹인 것과 같은 구조다.
#
# 한 번에 여러 종을 넣을 때는 이쪽이 훨씬 낫다 — 어드민에서 30번 올리는 대신
# 폴더에 넣고 push 한 번이면 된다. 대신 배포로만 바뀌므로, 운영 중에 한 종만
# 갈아끼울 때는 어드민 업로드가 편하다.
BUNDLED_ZIPS_DIR = Path(__file__).resolve().parent.parent.parent / "fontzips"


def zip_path(font_id: int) -> Path:
    """업로드가 저장되는 자리 (쓰기용)."""
    return ZIPS_DIR / f"font-{font_id:03d}.zip"


def resolve_zip(font_id: int):
    """실제로 내보낼 파일 (읽기용). 없으면 None.

    어드민이 올린 것이 저장소에 묶인 것을 이긴다 — 나중에 올린 쪽이 최신이다.
    """
    name = f"font-{font_id:03d}.zip"
    for p in (ZIPS_DIR / name, BUNDLED_ZIPS_DIR / name):
        try:
            if p.is_file():
                return p
        except OSError:
            pass
    return None


def has_zip(font_id: int) -> bool:
    """이 폰트에 내보낼 ZIP 이 있는가. 목록 조회에서 폰트마다 불리므로 가볍게."""
    return resolve_zip(font_id) is not None


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


def file_source_of(font_id: int) -> str:
    """이 폰트 파일의 출처. 'user'면 어드민이 직접 올린 파일이다.

    FONT_RESOLUTION은 기동 시 build_font_resolution이 채우고,
    업로드/삭제 때 갱신된다.

    프론트엔드가 이 값으로 '업로드 파일 vs 웹폰트' 우선순위를 정한다.
    'user'인데 웹폰트 설정도 남아 있으면 업로드 파일이 이긴다 —
    파일을 올렸다는 행위 자체가 그 파일을 쓰겠다는 뜻이기 때문이다.
    """
    r = FONT_RESOLUTION.get(font_id)
    return r[1] if r else ""


def file_version_of(font_id: int) -> int:
    """이 폰트 파일들의 '판'. 대표 파일과 굵기 파일 중 가장 최근 수정 시각이다.

    주소에 ?v= 로 붙여 캐시를 가른다. 어느 파일이든 바꾸면 값이 달라져 주소가
    바뀌므로, 1년 immutable로 내려도 교체가 즉시 반영된다.

    굵기 파일 하나만 바꿔도 대표 파일 주소까지 같이 바뀐다 — 필요 이상으로
    한 번 더 받게 되지만, 폰트 하나 분량이고 어드민이 파일을 바꿀 때만이다.
    """
    ts = 0
    for p in (font_path(font_id), bundled_font_path(font_id)):
        try:
            if p.exists():
                ts = max(ts, int(p.stat().st_mtime))
        except OSError:
            pass
    r = FONT_RESOLUTION.get(font_id)
    if r:
        try:
            ts = max(ts, int(Path(r[0]).stat().st_mtime))
        except OSError:
            pass
    try:
        for wp in FONTS_DIR.glob(f"font-{font_id:03d}-w*.woff2"):
            ts = max(ts, int(wp.stat().st_mtime))
    except OSError:
        pass
    for w in WEIGHT_RESOLUTION.get(font_id, []):
        try:
            ts = max(ts, int(Path(w["path"]).stat().st_mtime))
        except OSError:
            pass
    return ts


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

    # 이 폰트는 이제 '어드민 업로드'가 된다. 이후 /file 응답이 재검증 헤더로
    # 나가야 교체가 즉시 반영되므로, 여기서 반드시 갱신해 둔다.
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
    """DB FontWeight + 웹폰트 CDN + 매니페스트 WEIGHT_RESOLUTION + 대표 파일을 우선순위대로 병합.

    우선순위: DB(FontWeight, 어드민 개별 업로드) > 웹폰트 CDN(Google Fonts 등)
    > 매니페스트(대량 업로드) > 대표 파일 1건. 같은 weight 값은 한 번만 노출한다.

    ⚠️ 대표 파일(4순위) 추가 조건: 매니페스트(3순위)가 이미 이 폰트의 굵기 세트를
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

    # 2순위: 웹폰트 CDN 소스 (Google Fonts 등) — 파일 업로드 없이 등록된 굵기
    if font.webfont_family and font.webfont_weights:
        for part in font.webfont_weights.split(","):
            part = part.strip()
            if not part.isdigit():
                continue
            w = int(part)
            if w not in out:
                out[w] = {
                    "weight": w,
                    "label": WEIGHT_LABELS.get(w, str(w)),
                    "source": "webfont",
                    "has_file": True,
                    "path": None,
                }

    # 3순위: 기존 매니페스트 기반 대량 업로드 시스템
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

    # 4순위: 대표 파일 (primary_weight) — 매니페스트가 없는 폰트에서만 별도 추가
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


# 번들 폰트는 재배포로만 바뀌므로 1년 immutable이 맞다.
#
# 어드민이 올린 파일은 다르다. 파일을 교체해도 주소(/api/fonts/{id}/file)가
# 그대로라, immutable로 두면 브라우저와 CDN이 1년 내내 옛 바이트를 돌려준다.
# "어드민에서 폰트를 올렸는데 페이지가 안 바뀐다"의 실제 원인이었다.
# ETag 재검증으로 바꾼다 — 안 바뀌었으면 304라서 트래픽은 거의 같고,
# 바뀌면 즉시 반영된다. (no-store로 하면 190종을 매 방문마다 다시 받는다)
_CACHE_IMMUTABLE = {
    "Cache-Control": "public, max-age=31536000, immutable",
    "Access-Control-Allow-Origin": "*",
}
_CACHE_REVALIDATE = {
    "Cache-Control": "public, max-age=0, must-revalidate",
    "Access-Control-Allow-Origin": "*",
}


def _etag_of(path) -> str:
    st = Path(path).stat()
    return f'"f{int(st.st_mtime)}-{st.st_size}"'


def _serve_font(request: Request, path, headers: dict):
    """파일 하나를 내린다. If-None-Match 가 맞으면 304 — 본문을 안 보낸다.

    FileResponse는 ETag를 붙이기만 하고 조건부 요청을 검사하지 않는다. 그래서
    max-age=0, must-revalidate 로 내려도 브라우저가 매번 파일 전체를 다시 받았다
    (한글 폰트 평균 476KB × 화면에 보이는 수만큼, 방문할 때마다). 여기서 직접
    검사한다.
    """
    try:
        etag = _etag_of(path)
    except OSError:
        etag = None
    h = dict(headers)
    if etag:
        h["ETag"] = etag
        if etag in [t.strip() for t in (request.headers.get("if-none-match") or "").split(",")]:
            return Response(status_code=304, headers=h)
    return FileResponse(path=path, media_type="font/woff2", headers=h)


def _pick_font_file(font_id: int, weight: int = 0):
    """내려줄 파일 경로와, 버전 키 없이 내릴 때 쓸 캐시 헤더를 고른다."""
    if weight:
        # 1순위: 어드민이 개별 등록한 굵기 파일
        wp = weight_file_path(font_id, weight)
        if wp.exists():
            # 굵기 파일도 어드민 업로드다. 대표 파일이 번들이라 해서 이 파일까지
            # immutable로 내리면, 굵기 파일을 교체해도 반영되지 않는다.
            return wp, _CACHE_REVALIDATE
        # 2순위: 매니페스트 기반 굵기 파일 (저장소에 묶여 배포되므로 immutable)
        for w in WEIGHT_RESOLUTION.get(font_id, []):
            if w["weight"] == weight and Path(w["path"]).exists():
                return Path(w["path"]), _CACHE_IMMUTABLE
    resolved = FONT_RESOLUTION.get(font_id)
    if resolved and Path(resolved[0]).exists():
        headers = (_CACHE_REVALIDATE if file_source_of(font_id) == "user"
                   else _CACHE_IMMUTABLE)
        return Path(resolved[0]), headers
    p = font_path(font_id)
    if p.exists():
        FONT_RESOLUTION[font_id] = (str(p), "user")
        # 방금 'user'로 밝혀졌으므로 재검증 헤더로 내린다
        return p, _CACHE_REVALIDATE
    bp = bundled_font_path(font_id)
    if bp.exists():
        return bp, _CACHE_IMMUTABLE
    return None, None


@router.get("/{font_id}/file")
def download_font_file(request: Request, font_id: int, weight: int = 0,
                       v: str = "", preview: int = 0,
                       db: Session = Depends(get_db)):
    """v= 는 파일의 판(file_version_of)이다. 값 자체는 쓰지 않는다 — 주소를
    가르는 것이 일이다. 붙어 있으면 파일이 바뀌면 주소도 바뀌므로 1년
    immutable로 내려도 교체가 즉시 반영된다.

    v가 없는 옛 주소도 그대로 받는다. 그쪽은 예전대로 재검증인데, 이제는
    If-None-Match 를 실제로 검사해 304를 돌려준다.

    preview=1 은 '이 폰트를 미리보기로만 쓴다'는 뜻이다. 이름과 짧은 견본
    문구만 그리면 되므로 가벼운 서브셋을 내려준다 (app/font_subset.py).
    아직 서브셋이 안 만들어졌으면 원본을 그대로 준다 — 요청을 기다리게
    하지 않는다.
    """
    path, headers = _pick_font_file(font_id, weight)
    if path is None:
        raise HTTPException(status_code=404, detail="폰트 파일이 없습니다")

    if preview:
        from ..font_subset import subset_or_none
        sub = subset_or_none(path)
        if sub is not None:
            path = sub
        elif v:
            # 서브셋이 아직 없어 원본을 내보내는 중이다. 이때 1년 immutable 로
            # 내리면 이 주소에 원본이 박제돼, 서브셋이 만들어져도 영영 안 쓰인다.
            # 짧게 주고 다음 방문 때 다시 물어보게 한다.
            return _serve_font(request, path, _CACHE_REVALIDATE)

    return _serve_font(request, path, _CACHE_IMMUTABLE if v else headers)



@router.get("/{font_id}/file/{name}")
def download_font_file_by_path(request: Request, font_id: int, name: str):
    """굵기를 경로에 담은 폰트 파일 주소.  /api/fonts/58/file/100.woff2

    ⚠ 왜 굵기를 쿼리스트링에 두지 않는가
      앞단 CDN이 **쿼리스트링을 무시하고 경로만으로 캐싱**한다. 그래서
      /file?weight=100 과 /file?weight=700 이 같은 캐시 항목이 되어,
      굵기가 여러 종인 폰트가 전부 같은 파일 하나로 나갔다.
      실측(2026-09-02): 아리따 돋움 100·400·700·900 이 전부 같은 ETag였고,
      더잠실체 100·400·800 도 마찬가지였다. 웹폰트에서 굵기 구분이
      아예 되지 않는 상태였다.

      같은 이유로 캐시 항목이 낡으면 헤더도 같이 낡는다. CORS 설정을 고쳐
      배포해도 CDN에 남은 옛 응답이 계속 나가서, 홍보물 HTML(file://)에서
      웹폰트가 "A network error occurred" 로 실패했다. 주소를 새로 만들면
      캐시 항목도 새로 생기므로 그 문제까지 같이 풀린다.

    name 은 "300.woff2" 또는 "300" 을 받는다. 확장자는 주소만 봐도 폰트인 줄
    알도록 붙이는 것이고, 값 자체는 앞의 숫자다.

    옛 주소(/file?weight=)도 그대로 둔다 — 이미 나간 홍보물이 깨지면 안 된다.
    """
    stem = name[:-6] if name.lower().endswith(".woff2") else name
    try:
        weight = int(stem)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="굵기는 숫자여야 합니다. 예: /file/300.woff2")
    if not 0 <= weight <= 1000:
        raise HTTPException(status_code=400, detail="굵기는 0 ~ 1000 입니다")

    path, _headers = _pick_font_file(font_id, weight)
    if path is None:
        raise HTTPException(status_code=404, detail="폰트 파일이 없습니다")
    # 주소에 굵기가 박혀 있어, 파일이 바뀌지 않는 한 내용도 바뀌지 않는다.
    return _serve_font(request, path, _CACHE_IMMUTABLE)

# ═══════════════════════════════════════════════════════════
# 외부용 웹폰트 CSS  GET /api/fonts/{id}/webfont.css?key=...
# ═══════════════════════════════════════════════════════════
# 홍보물·프레스킷처럼 폰트픽 바깥에서 폰트를 그대로 렌더링해야 할 때 쓴다.
# @font-face 한 덩어리를 CORS 허용 헤더와 함께 내려주므로, 로컬 HTML 파일에서도
# <link>만 걸면 폰트가 적용된다.
#
# ⚠ 키를 요구하는 이유
#   폰트픽에는 재배포 금지 라이선스 폰트가 있다. 특히 와이즈폰트 자사 폰트는
#   배포 페이지에 "다른 웹사이트나 서버에 올려 직접 배포 금지"라고 명시돼 있다.
#   이 엔드포인트를 무조건 열면 누구나 폰트픽을 폰트 CDN으로 쓸 수 있게 되고,
#   그건 폰트픽이 스스로 그 조건을 무너뜨리는 셈이다.
#
#   주소를 공개하지 않는 것만으로는 막히지 않는다 — 브라우저가 실제로 부르는
#   순간 개발자도구 네트워크 탭, 서버 로그, 히스토리에 주소가 남는다.
#
#   다만 이 방식이 완전한 차단은 아니다. 키는 홍보물 HTML 안에 문자열로 들어가므로
#   그 파일을 받은 사람은 소스를 열어 볼 수 있다. 막아 주는 것은 '주소만 알게 된
#   제3자'이고, 유출이 의심되면 환경변수만 바꾸면 즉시 무효가 된다.
#
# 키 설정: 카페24 프로젝트 환경변수에 WEBFONT_CSS_KEY 를 넣는다.
#          값이 비어 있으면 엔드포인트 자체가 404로 닫힌다(실수로 열리는 것 방지).
WEBFONT_CSS_KEY = os.getenv("WEBFONT_CSS_KEY", "").strip()

# 로컬 파일(file://)에서 열면 Origin이 "null"로 온다. 그래서 도메인 화이트리스트가
# 통하지 않아 * 로 열어야 한다 — 접근 제어는 위의 키가 담당한다.
_WEBFONT_CSS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    # 폰트 파일 자체는 별도 캐시 정책을 따르고, CSS는 짧게 잡는다.
    # 어드민에서 굵기를 추가하면 그만큼 빨리 반영돼야 한다.
    "Cache-Control": "public, max-age=300",
}


@router.get("/{font_id}/webfont.css")
def webfont_css(font_id: int, key: str = "", db: Session = Depends(get_db)):
    """이 폰트의 @font-face 규칙을 CSS로 내려준다 (외부 사용).

    사용 예:
        <link rel="stylesheet"
              href="{SITE_URL}/api/fonts/62/webfont.css?key=발급키">
        <style> h1 { font-family: 'FFP-062', sans-serif; } </style>

    font-family 이름은 폰트픽 내부와 같은 규칙(FFP-{id:03d})을 쓴다.
    응답 첫 줄 주석에 폰트명과 family 이름을 적어 두므로 그대로 복사하면 된다.
    """
    if not WEBFONT_CSS_KEY:
        # 키가 설정되지 않은 서버에서는 기능 자체가 없는 것처럼 둔다.
        raise HTTPException(status_code=404, detail="Not Found")
    if key != WEBFONT_CSS_KEY:
        raise HTTPException(status_code=403, detail="유효하지 않은 키입니다")

    font = db.query(Font).filter(Font.id == font_id).first()
    if font is None:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    family = _ffp_family(font_id)
    lines = [
        f"/* 폰트픽 웹폰트 — {font.name} ({font.maker or ''})",
        f"   font-family: '{family}'",
        f"   상세: {SITE_URL}/font/{font_id}",
        "   ⚠ 폰트 라이선스는 각 배포처 조건을 따릅니다. 파일 재배포는 하지 마세요. */",
    ]

    # 굵기별 규칙. _merged_weights 는 어드민 등록·매니페스트·대표 파일을
    # 우선순위대로 합쳐 주므로 상세페이지와 같은 굵기 구성이 나온다.
    weights = [w for w in _merged_weights(font) if w.get("source") != "webfont"]
    if weights:
        for w in weights:
            lines.append(
                f"@font-face{{font-family:'{family}';"
                f"src:url('/api/fonts/{font_id}/file/{w['weight']}.woff2') format('woff2');"
                f"font-weight:{w['weight']};font-style:normal;font-display:swap}}"
            )
    elif font.has_file:
        # 굵기 정보가 없는 폰트 — 대표 파일 하나만 등록한다
        lines.append(
            f"@font-face{{font-family:'{family}';"
            f"src:url('/api/fonts/{font_id}/file/0.woff2') format('woff2');"
            f"font-weight:normal;font-style:normal;font-display:swap}}"
        )
    else:
        # 웹폰트 CDN으로만 등록된 폰트는 내려줄 파일이 없다.
        # 빈 CSS 대신 이유를 주석으로 남긴다 — 안 되는 이유를 찾느라 헤매지 않게.
        lines.append(
            f"/* 이 폰트는 파일이 없습니다. 외부 CDN 웹폰트로 등록돼 있으므로"
            f" 제작사 CSS를 직접 사용하세요: {font.webfont_css_url or '(주소 미등록)'} */"
        )

    # 상대경로(/api/...)는 외부 문서에서 안 통한다. 절대주소로 바꿔 내려준다.
    # 주소는 app/site.py 한 곳에서 온다 — 도메인을 옮기면 여기서 나가는
    # CSS 도 같이 따라가야 남의 사이트에 박힌 임베드가 안 깨진다.
    css = "\n".join(lines).replace("url('/api/", "url('%s/api/" % SITE_URL)
    return Response(content=css, media_type="text/css", headers=_WEBFONT_CSS_HEADERS)


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


# ══════════════════════════════════════════════════════════════
# 배포용 ZIP
# ══════════════════════════════════════════════════════════════

@router.post("/{font_id}/zip")
async def upload_font_zip(
    font_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    """어드민이 배포용 폰트 묶음을 올린다."""
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="ZIP 파일만 올릴 수 있습니다")

    try:
        content = await file.read()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"파일을 읽을 수 없어요: {e}")

    if not content:
        raise HTTPException(status_code=400, detail="빈 파일입니다")
    if len(content) > MAX_ZIP_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"파일이 너무 큽니다 (최대 {MAX_ZIP_SIZE // 1024 // 1024}MB). "
                   f"올리신 파일은 {len(content) / 1024 / 1024:.1f}MB 입니다.",
        )
    # 확장자만 믿지 않는다. 이름만 .zip 인 파일을 받아 두면 사용자가 눌렀을 때
    # 열리지 않는 파일이 내려가고, 그 사실을 아무도 모른 채 남는다.
    if not content.startswith(b"PK"):
        raise HTTPException(
            status_code=400,
            detail="ZIP 파일이 아닙니다. 압축 파일이 맞는지 확인해 주세요.",
        )

    out = zip_path(font_id)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"파일 저장 실패 (디스크 권한 문제일 수 있어요): {type(e).__name__}: {e}",
        )
    return {"font_id": font_id, "size": len(content), "has_zip": True}


@router.delete("/{font_id}/zip", status_code=status.HTTP_204_NO_CONTENT)
def delete_font_zip(
    font_id: int,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")
    # 지울 수 있는 것은 어드민이 올린 것뿐이다. 저장소에 묶여 배포된 ZIP 은
    # 파일을 지워도 다음 배포에 되살아나므로 손대지 않는다
    # (폰트 파일의 delete_font_file 이 번들 파일을 다루는 방식과 같다).
    p = zip_path(font_id)
    if p.exists():
        p.unlink()


@router.get("/{font_id}/download")
def download_font_zip(font_id: int, db: Session = Depends(get_db)):
    """상세페이지 다운로드 버튼이 여는 주소. 누르면 바로 파일이 내려간다.

    FileResponse 는 파일을 통째로 메모리에 올리지 않고 흘려보내므로, 큰
    파일이어도 워커 메모리를 붙잡지 않는다.
    """
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    # 재배포를 막아 둔 폰트는 여기서도 끊는다. 버튼이 이미 제작사 배포처로
    # 가지만, 이 주소는 규칙만 알면 직접 부를 수 있고 예전 링크도 남아 있다.
    # 404 대신 배포처로 보내 주는 편이 받으러 온 사람에게 쓸모 있다.
    official = NO_REDISTRIBUTE.get(font_id)
    if official:
        return RedirectResponse(official, status_code=302)

    p = resolve_zip(font_id)
    if p is None:
        raise HTTPException(status_code=404, detail="이 폰트에는 올려둔 파일이 없습니다")

    # 받는 사람에게는 font-062.zip 이 아니라 폰트 이름으로 보여야 한다.
    # 한글·공백이 섞인 이름은 Starlette 가 RFC 5987 로 안전하게 인코딩한다.
    name = (font.name or f"font-{font_id}").strip() or f"font-{font_id}"
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "")
    return FileResponse(
        p,
        media_type="application/zip",
        filename=f"{name}.zip",
    )
