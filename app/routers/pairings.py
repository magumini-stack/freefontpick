"""폰트 페어링 API

- GET /api/pairings                 : 전체 페어링 (테마별 정렬) — 공개
- GET /api/fonts/{font_id}/pairings : 특정 폰트가 포함된 페어링 — 공개
- GET /api/pairings/themes          : 전체 테마 이름 목록 — 공개 (어드민 드롭다운용)
- GET /api/pairings/auto-generate   : 조합 자동 생성 (저장 안 함) — 공개
- POST /api/pairings                : 페어링 생성 — 관리자
- PATCH /api/pairings/{id}          : 페어링 수정 — 관리자
- DELETE /api/pairings/{id}         : 페어링 삭제 — 관리자
- POST /api/pairings/purge-orphans  : orphan 정리 — 관리자
- POST /api/pairings/regenerate-all : 전체 재생성·교체 — 관리자
"""
import math
import random
import re
from collections import Counter
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..font_metrics import metrics_of
from ..models import Font, FontPairing
from ..auth import require_password_changed
from ..schemas import PairingCreate, PairingUpdate

router = APIRouter(prefix="/api", tags=["pairings"])


def _font_brief(f: Font) -> dict:
    from .files import _merged_weights, file_source_of
    weights = _merged_weights(f)
    return {
        "id": f.id,
        "name": f.name,
        "maker": f.maker or "",
        "stack": f.stack or "'Nanum Gothic',sans-serif",
        "has_file": bool(f.has_file),
        "is_english": bool(f.is_english),
        "webfont_family": f.webfont_family or None,
        "webfont_css_url": f.webfont_css_url or None,
        # 프론트의 resolveWebfont가 이 값으로 "어드민이 올린 파일이 웹폰트보다
        # 우선"을 판단한다. 없으면 undefined !== 'user'가 항상 참이 되어
        # 업로드된 파일을 두고 CDN 웹폰트로 렌더한다.
        "file_source": file_source_of(f.id),
        "available_weights": [w["weight"] for w in weights],
    }


def _to_out(p: FontPairing):
    # 참조하던 폰트가 삭제/재등록으로 사라진 orphan 페어링은 응답에서 제외.
    # (없으면 /api/pairings가 500을 뱉어 어드민 전체가 로딩 실패했다.)
    if p.title_font is None or p.body_font is None:
        return None
    return {
        "id": p.id,
        "theme": p.theme,
        "sample_title": p.sample_title or "",
        "sample_body": p.sample_body or "",
        "description": p.description or "",
        "title_weight": int(getattr(p, "title_weight", 700) or 700),
        "body_weight": int(getattr(p, "body_weight", 400) or 400),
        "sort_order": p.sort_order,
        "title_font": _font_brief(p.title_font),
        "body_font": _font_brief(p.body_font),
    }


@router.get("/pairings")
def list_pairings(db: Session = Depends(get_db)) -> List[dict]:
    rows = (
        db.query(FontPairing)
        .order_by(FontPairing.sort_order, FontPairing.id)
        .all()
    )
    return [d for d in (_to_out(p) for p in rows) if d]


@router.get("/pairings/themes")
def list_pairing_themes(db: Session = Depends(get_db)) -> List[str]:
    """등록된 페어링 테마 이름 전체 (어드민 드롭다운/자동완성용)."""
    rows = db.query(FontPairing.theme).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


@router.get("/fonts/{font_id}/pairings")
def font_pairings(font_id: int, db: Session = Depends(get_db)) -> List[dict]:
    """해당 폰트가 제목 또는 본문으로 들어간 조합. 없으면 빈 배열.

    프론트엔드가 상위 6개만 잘라 보여주므로, 같은 폰트가 수십 개 조합에
    쓰이는 경우(수트/프리텐다드/나눔스퀘어/노토산스/나눔고딕 등) 항상 옛날
    조합만 노출되고 새로 추가된 굵기 활용 조합(v5, 모던 미니멀 제목/굵은
    산세리프 슬로건/큰 안내 본문)은 뒤로 밀려 절대 안 보이는 문제가 있었다.
    해당 폰트가 이 조합에서 700 이상 굵기로 쓰인 경우를 "굵기 활용 조합"으로
    보고 우선 정렬해 상위 6개 안에 반드시 포함되도록 한다.
    """
    rows = (
        db.query(FontPairing)
        .filter(or_(
            FontPairing.title_font_id == font_id,
            FontPairing.body_font_id == font_id,
        ))
        .order_by(FontPairing.sort_order, FontPairing.id)
        .all()
    )

    def _is_weight_showcase(p: FontPairing) -> bool:
        if p.title_font_id == font_id and (p.title_weight or 0) >= 700:
            return True
        if p.body_font_id == font_id and (p.body_weight or 0) >= 700:
            return True
        return False

    rows.sort(key=lambda p: (0 if _is_weight_showcase(p) else 1, p.sort_order, p.id))
    return [d for d in (_to_out(p) for p in rows) if d]


@router.get("/debug/font-audit")
def font_audit(rebuild: int = 0, db: Session = Depends(get_db)) -> dict:
    """폰트별 서빙 파일 소스 점검 (문제 폰트 전수조사용).

    ?rebuild=1 을 붙이면 해석 캐시를 다시 계산.
    """
    from .files import FONT_AUDIT, WEIGHT_RESOLUTION, WEIGHT_UNMATCHED, build_font_resolution
    summary = None
    if rebuild or not FONT_AUDIT:
        summary = build_font_resolution(db)
    problems = [e for e in FONT_AUDIT if e["source"] in ("none",) or e.get("note")]
    return {
        "summary": summary or {
            "total": len(FONT_AUDIT),
            "user": sum(1 for e in FONT_AUDIT if e["source"] == "user"),
            "bundled_by_name": sum(1 for e in FONT_AUDIT if e["source"] == "bundled-by-name"),
            "bundled_by_id": sum(1 for e in FONT_AUDIT if e["source"] == "bundled-by-id"),
            "missing": sum(1 for e in FONT_AUDIT if e["source"] == "none"),
            "weight_fonts": len(WEIGHT_RESOLUTION),
            "weight_unmatched": WEIGHT_UNMATCHED,
        },
        "problems": problems,
        "all": FONT_AUDIT,
    }


# ═══════════════════════════════════════════════════════
# 어드민 CRUD — 페어링 관리
# ═══════════════════════════════════════════════════════

def _get_font_or_400(db: Session, font_id: int, label: str) -> Font:
    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=400, detail=f"존재하지 않는 {label} 폰트입니다")
    return font


@router.post("/pairings", status_code=status.HTTP_201_CREATED)
def create_pairing(
    payload: PairingCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    _get_font_or_400(db, payload.title_font_id, "제목")
    _get_font_or_400(db, payload.body_font_id, "본문")
    p = FontPairing(
        theme=payload.theme,
        title_font_id=payload.title_font_id,
        body_font_id=payload.body_font_id,
        sample_title=payload.sample_title,
        sample_body=payload.sample_body,
        description=payload.description,
        title_weight=payload.title_weight,
        body_weight=payload.body_weight,
        sort_order=payload.sort_order,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.patch("/pairings/{pairing_id}")
def update_pairing(
    pairing_id: int,
    payload: PairingUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    p = db.query(FontPairing).filter(FontPairing.id == pairing_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="페어링을 찾을 수 없습니다")
    data = payload.model_dump(exclude_unset=True)
    if "title_font_id" in data:
        _get_font_or_400(db, data["title_font_id"], "제목")
    if "body_font_id" in data:
        _get_font_or_400(db, data["body_font_id"], "본문")
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.delete("/pairings/{pairing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pairing(
    pairing_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    p = db.query(FontPairing).filter(FontPairing.id == pairing_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="페어링을 찾을 수 없습니다")
    db.delete(p)
    db.commit()


@router.post("/pairings/purge-orphans")
def purge_orphan_pairings(
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
) -> dict:
    """참조하던 폰트가 사라진(삭제/재등록으로 ID가 바뀐) orphan 페어링을 일괄 삭제.

    폰트 삭제 시 페어링을 CASCADE로 정리하지 않는 스키마 특성상,
    폰트를 삭제하면 그 폰트를 title/body로 쓰던 페어링이 orphan으로 남아
    /api/pairings 응답 생성 시 500을 유발한다. 응답 단계에서는 조용히 걸러내지만,
    DB에도 남아 있으면 어드민 카운트가 부풀고 관리가 어려우므로 이 엔드포인트로 정리한다.
    """
    all_pairings = db.query(FontPairing).all()
    removed_ids = []
    for p in all_pairings:
        if p.title_font is None or p.body_font is None:
            removed_ids.append(p.id)
            db.delete(p)
    db.commit()
    return {"removed": len(removed_ids), "ids": removed_ids}


# ═══════════════════════════════════════════════════════
# 자동 페어링 생성 — 폰트 메타(무드/용도/업종/성격/굵기감/격식/문장길이)
# + 카테고리 태그를 점수화해서 어울리는 상대 폰트를 찾아 3개 이상 추천한다.
#
# 테마·샘플 문구는 하드코딩하지 않고, 이미 DB에 등록된 페어링들에서
# 실제 사용 중인 (테마 → 샘플 문구 목록)을 수집해서 후보마다 다르게 배정한다.
# 그래야 19개 테마와 그 안의 다양한 문구가 골고루 노출된다.
# ═══════════════════════════════════════════════════════

_TITLE_USAGE = {"제목", "캐치프레이즈", "로고", "썸네일", "포스터"}
_BODY_USAGE = {"본문", "정보전달", "출판", "UI"}

# 폰트 메타의 usage/mood를 실제 테마(문자열)로 잇는 힌트.
# 값은 "테마 이름에 들어갈 법한 키워드" — DB 테마명과 부분일치로 매칭한다.
_USAGE_THEME_HINTS = {
    "썸네일": ["썸네일"],
    "제목": ["포스터", "슬로건", "제목", "배너"],
    "포스터": ["포스터", "안내문", "배너"],
    "캐치프레이즈": ["슬로건", "브랜딩", "로고"],
    "로고": ["로고", "명함", "브랜딩", "브랜드"],
    "본문": ["본문", "블로그", "매거진", "안내 본문"],
    "정보전달": ["카드뉴스", "안내", "관공서", "포스터"],
    "출판": ["매거진", "블로그", "본문"],
    "UI": ["미니멀", "본문"],
    "SNS카드": ["카드뉴스", "SNS", "릴스", "숏폼"],
    "영상자막": ["자막", "브이로그", "릴스", "숏폼"],
    "패키지": ["브랜딩", "감성"],
}

# 무드 → 테마 키워드 (usage로 못 잡을 때 보조)
_MOOD_THEME_HINTS = {
    "감성적": ["감성", "캘리", "손글씨", "웨딩"],
    "고급스러운": ["웨딩", "브랜딩", "미니멀"],
    "부드러운": ["캘리", "감성", "키즈"],
    "친근한": ["브이로그", "키즈", "반려동물"],
    "장난스러운": ["키즈", "반려동물", "릴스"],
    "임팩트": ["썸네일", "슬로건", "이벤트", "프로모션"],
    "강인한": ["썸네일", "슬로건", "이벤트"],
    "신뢰감": ["관공서", "시니어", "안내"],
    "깔끔한": ["미니멀", "본문", "카드뉴스"],
    "현대적": ["미니멀", "본문"],
    "독특한": ["포인트", "손글씨"],
}

# 산업(industry) → 테마 키워드
# 어드민에 이미 촘촘히 등록돼 있어서, usage/mood와 함께 반영하면 테마 분산 효과가 크다.
_INDUSTRY_THEME_HINTS = {
    "카페": ["감성", "브랜딩", "메뉴"],
    "푸드": ["메뉴", "브랜딩", "감성"],
    "뷰티": ["감성", "브랜딩", "웨딩"],
    "패션": ["브랜딩", "감성", "미니멀"],
    "키즈": ["키즈", "반려동물"],
    "교육": ["카드뉴스", "안내", "관공서"],
    "헬스케어": ["안내", "관공서", "본문"],
    "IT": ["미니멀", "본문", "UI"],
    "공공기관": ["관공서", "안내", "시니어"],
    "이벤트": ["이벤트", "프로모션", "배너", "슬로건"],
    "출판": ["매거진", "블로그", "본문"],
}

# 성격(personality) → 테마 키워드
_PERSONALITY_THEME_HINTS = {
    "중성적": ["본문", "미니멀"],
    "남성적": ["슬로건", "썸네일", "이벤트"],
    "여성적": ["웨딩", "감성", "브랜딩"],
    "어린이": ["키즈", "반려동물"],
    "전통적": ["관공서", "매거진", "웨딩"],
    "현대적": ["미니멀", "본문", "UI"],
    "복고적": ["감성", "브랜딩"],
    "미래적": ["미니멀", "슬로건", "이벤트"],
    "강한": ["슬로건", "썸네일", "이벤트", "포스터"],
}

# 격식(formality) → 테마 키워드
_FORMALITY_THEME_HINTS = {
    "매우 격식": ["관공서", "웨딩", "매거진"],
    "격식": ["관공서", "본문", "안내"],
    "중간": ["본문", "카드뉴스", "브랜딩"],
    "캐주얼": ["브이로그", "SNS", "릴스"],
    "매우 캐주얼": ["키즈", "릴스", "반려동물"],
}

# 영문 전용 카테고리 태그 — 이 태그가 붙은 폰트는 영문 폰트로 간주하고
# 한글 폰트와의 자동 페어링에서 제외한다 (반대 방향도 마찬가지).
_ENGLISH_ONLY_TAGS = {"디자인 영어", "디자이너 필수 영문"}

# 조합 추천에서 아예 빼는 폰트의 태그.
# '펜시'는 장식성이 매우 강해 제목으로도 본문으로도 다른 폰트와 붙이기 어렵다.
# 실제로 어드민이 큐레이션한 285건에서 단 한 번도 쓰이지 않았다 — 사람이 이미
# 내린 판단을 알고리즘에도 반영한다.
_EXCLUDED_TAGS = {"펜시"}

# 영문 전용 폰트가 한글 폰트와 붙을 때 쓰는 테마.
# 이 테마의 문구 뱅크는 (영문 제목, 한글 본문) 형태라 그대로 들어맞는다.
_MIXED_LANG_THEME = "한글 + 영문 조합"

# 영문끼리 붙을 때 쓰는 테마 (문구가 제목·본문 모두 영문).
from ..pairing_phrases import ENGLISH_THEMES as _ENGLISH_THEMES


def _is_excluded(font: "Font") -> bool:
    return bool({t.name for t in font.tags} & _EXCLUDED_TAGS)


def _is_english_only(font: "Font") -> bool:
    """카테고리 태그로 이 폰트가 영문 전용인지 판별."""
    tags = {t.name for t in (font.tags or [])}
    return bool(tags & _ENGLISH_ONLY_TAGS)


# 카테고리 태그가 제목/본문 어느 쪽에 더 잘 맞는지에 대한 힌트.
# 메타(무드/용도 등)가 부실해도 어드민이 직접 고른 태그는 대체로 신뢰도가 높다.
_TAG_TITLE_HINTS = {
    "시선을 끄는 제목용", "유튜브 썸네일 추천", "로고디자인", "독특한",
    "캘리그라피", "펜시", "귀여운", "꽉찬고딕",
    # 2026-08 신 태그 체계
    "네모틀 고딕", "디스플레이", "장식", "독특한 세리프", "제목용 굴림",
}
_TAG_BODY_HINTS = {
    "가독성 좋은 고딕", "정보전달 본문용", "UI/UX/Web", "부드러운 명조",
    "부드러운 굴림", "또박또박 손글씨", "카드뉴스용",
    # 2026-08 신 태그 체계
    "제목-본문용 고딕", "부드러운 바탕", "손글씨", "본문용 영어",
}

# 태그로부터 대략적인 서체 모양(세리프/산세리프/손글씨/디스플레이)을 추정.
# 같은 모양끼리는 톤이 자연스럽게 어울리고, display 계열은 제목에, serif/sans는
# 본문 가독성에 강점이 있다는 일반적인 타이포그래피 관행을 반영한다.
_SHAPE_TAG_MAP = {
    "부드러운 명조": "serif",
    "가독성 좋은 고딕": "sans", "꽉찬고딕": "sans", "부드러운 굴림": "sans", "UI/UX/Web": "sans",
    "또박또박 손글씨": "script", "캘리그라피": "script", "펜시": "script", "귀여운": "script",
    "시선을 끄는 제목용": "display", "유튜브 썸네일 추천": "display", "로고디자인": "display",
    # 2026-08 신 태그 체계
    "부드러운 바탕": "serif", "독특한 세리프": "serif",
    "제목-본문용 고딕": "sans", "네모틀 고딕": "sans", "제목용 굴림": "sans", "본문용 영어": "sans",
    "손글씨": "script",
    "디스플레이": "display", "장식": "display", "디자인 영어": "display",
}


def _font_tags(font: Font) -> list:
    return [t.name for t in (font.tags or [])]


def _font_shape(tags: list) -> str:
    counts: dict = {}
    for t in tags:
        shape = _SHAPE_TAG_MAP.get(t)
        if shape:
            counts[shape] = counts.get(shape, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)


def _title_fit(font: Font) -> float:
    meta = font.meta or {}
    tags = _font_tags(font)
    usage = set(meta.get("usage") or [])
    score = 0.0
    if usage & _TITLE_USAGE:
        score += 3
    if meta.get("weight_feel") == "굵음":
        score += 2
    if meta.get("reading_length") == "짧은 글자":
        score += 2
    if usage & _BODY_USAGE:
        score -= 1
    # A: 카테고리 태그 반영
    score += 2.0 * len(set(tags) & _TAG_TITLE_HINTS)
    # D: 모양 축 — display/script 계열은 제목에 강점
    shape = _font_shape(tags)
    if shape == "display":
        score += 2
    elif shape == "script":
        score += 1
    return score


def _body_fit(font: Font) -> float:
    meta = font.meta or {}
    tags = _font_tags(font)
    usage = set(meta.get("usage") or [])
    score = 0.0
    if usage & _BODY_USAGE:
        score += 3
    if meta.get("reading_length") == "장문 가능":
        score += 3
    if meta.get("weight_feel") == "보통":
        score += 1
    if usage & {"제목", "로고", "썸네일"}:
        score -= 1
    # A: 카테고리 태그 반영
    score += 2.0 * len(set(tags) & _TAG_BODY_HINTS)
    # D: 모양 축 — 세리프/산세리프 계열은 본문 가독성에 강점
    shape = _font_shape(tags)
    if shape in ("serif", "sans"):
        score += 1.5
    return score


def _cohesion(font_a: Font, font_b: Font) -> float:
    meta_a, meta_b = font_a.meta or {}, font_b.meta or {}
    score = 0.0
    for dim in ("mood", "usage", "industry"):
        a = set(meta_a.get(dim) or [])
        b = set(meta_b.get(dim) or [])
        score += len(a & b)
    fa, fb = meta_a.get("formality"), meta_b.get("formality")
    if fa and fb:
        if fa == fb:
            score += 2
        elif {fa, fb} == {"격식", "캐주얼"}:
            score -= 2
    # A: 카테고리 태그 겹침도 궁합 점수에 반영 (메타가 비어있는 폰트도 구제)
    tags_a, tags_b = set(_font_tags(font_a)), set(_font_tags(font_b))
    score += 1.5 * len(tags_a & tags_b)
    # D: 같은 모양 계열이면 톤이 자연스럽게 어울림
    shape_a, shape_b = _font_shape(list(tags_a)), _font_shape(list(tags_b))
    if shape_a and shape_a == shape_b:
        score += 1
    return score


def _collect_theme_samples(db: Session) -> dict:
    """테마 → [(제목문구, 본문문구), ...] 문구 풀.

    두 소스를 합친다:
      1) DB에 저장된 기존 페어링의 샘플 문구 (어드민이 직접 쓴 것)
      2) `pairing_phrases.THEME_PHRASE_BANK` — 코드에 내장한 문구 뱅크

    예전에는 1)만 썼기 때문에 테마당 문구가 5~16개에 그쳤다. 뱅크를 합쳐
    테마마다 20개 이상의 후보를 확보해, 같은 폰트를 여러 번 조회해도 매번
    다른 문구가 나오도록 한다.

    ⚠️ 문구에 특정 폰트 이름이 들어 있으면 제외한다.
    문구 풀은 테마 단위로 공유되므로, A조합용으로 쓴 문장이 B조합 카드에 붙는다.
    실제로 "나눔스퀘어의 각진 볼드가 … KoPub돋움이 정보를 전달합니다" 같은
    문구가 전혀 다른 두 폰트 카드에 얹혀 사용자에게 틀린 정보를 주고 있었다.
    (운영 DB 285건 중 3건 — 테마별 풀이 작아 첫 조회에서 바로 튀어나왔다.)
    """
    from ..pairing_phrases import THEME_PHRASE_BANK, THEME_ALIASES

    # 테마명은 여기서 정규화한다. 운영 DB에는 같은 성격의 테마가 두 표기로
    # 갈려 있었다 ("포스터·배너" 86건 vs "포스터 · 안내문" 66건,
    # "SNS 카드뉴스" 55건 vs "카드뉴스 · SNS" 52건). 예전에는 별칭을 문구 풀을
    # 합칠 때만 썼기 때문에, 생성 결과에도 옛 표기가 그대로 따라붙어
    # 어드민 테마 목록이 두 벌로 보였다. 풀의 키 자체를 정규명으로 두면
    # 프로파일·선택·저장이 전부 정규명으로 흐른다.
    pool: dict = {}

    # 폰트 이름 집합. 2글자 이하는 일반 단어와 겹쳐 오탐이 나므로 제외한다.
    # 이름마다 `in`을 돌리면 문구 500개 × 폰트 200종 = 10만 번 스캔이라
    # 이 함수 시간의 27%를 먹었다. 정규식 하나로 합쳐 문구당 한 번만 훑는다.
    names = sorted(
        (n.strip() for (n,) in db.query(Font.name).all() if n and len(n.strip()) >= 3),
        key=len, reverse=True,
    )
    name_re = re.compile("|".join(re.escape(n) for n in names)) if names else None

    def _names_a_font(text: str) -> bool:
        return bool(name_re.search(text)) if name_re else False

    def _add(theme: str, st: str, sb: str):
        if not theme or (not st and not sb):
            return
        if _names_a_font(st) or _names_a_font(sb):
            return
        theme = THEME_ALIASES.get(theme, theme)      # 정규명으로 통일
        bucket = pool.setdefault(theme, [])
        if (st, sb) not in bucket:
            bucket.append((st, sb))

    # 세 컬럼만 쓴다. FontPairing은 title_font/body_font가 lazy="joined"이고
    # 그게 다시 tags/extra_weights 조인을 연쇄시켜, .all()로 받으면 문구 세 개를
    # 얻으려고 4중 중첩 조인을 통째로 끌어온다.
    for theme, st, sb in db.query(
        FontPairing.theme, FontPairing.sample_title, FontPairing.sample_body
    ):
        _add((theme or "").strip(), (st or "").strip(), (sb or "").strip())

    # 뱅크 병합 — DB에 존재하는 테마에만 붙인다(쓰이지 않는 테마를 새로 만들지 않음).
    # 위에서 키를 이미 정규화했으므로 뱅크 이름과 그대로 맞는다.
    for theme in list(pool.keys()):
        for st, sb in THEME_PHRASE_BANK.get(theme, []):
            _add(theme, st, sb)

    # 영문 테마는 DB에 없어도 항상 넣는다. 위 병합은 "DB에 이미 있는 테마"에만
    # 뱅크를 붙이는데, 영문 테마는 신규라 DB에 한 건도 없어 그 규칙으로는
    # 영원히 풀에 들어오지 못한다. 영문끼리 붙는 조합이 쓸 문구가 여기뿐이다.
    from ..pairing_phrases import ENGLISH_THEMES
    for theme in ENGLISH_THEMES:
        for st, sb in THEME_PHRASE_BANK.get(theme, []):
            _add(theme, st, sb)

    if not pool:
        pool["추천 조합"] = [("어울리는 조합을 찾았어요", "제목과 본문에 함께 써보세요")]
    return pool


# ── 문구 고르기: 최근에 나간 것을 피한다 ────────────────────────────
#
# "다른 조합 보기"를 누르는 것이 이 기능의 핵심 동작인데, 테마당 문구 풀이
# 24~35개뿐이라 무작위로만 뽑으면 재생성 두세 번 만에 같은 문구가 다시 나온다.
# 사용자 입장에서는 새로 만든 것 같지 않다.
#
# 그래서 테마별로 최근에 내보낸 문구를 기억해 두고 그 밖에서 먼저 고른다.
# 프로세스 메모리에만 두는 이유:
#   - 문구 다양성은 "직전 몇 번"만 피하면 충분하고, 영속화할 가치가 없다.
#   - 컨테이너가 여러 개여도 각자 자기 기록으로 잘 동작한다(최악이 현재 수준).
# 풀보다 기억을 짧게 잡아야 후보가 0개가 되지 않는다 → maxlen을 풀 크기의 절반으로.
_RECENT_SAMPLES: dict = {}
_RECENT_RATIO = 0.5      # 풀의 이 비율만큼을 "최근"으로 보고 회피
_RECENT_CAP = 16         # 풀이 커도 이 이상은 기억하지 않는다


def _pick_sample(theme: str, samples: list, used_in_response: set) -> tuple:
    """이번 응답에서 쓴 문구 + 최근 응답에 나간 문구를 피해서 하나 고른다."""
    from collections import deque

    recent = _RECENT_SAMPLES.get(theme)
    want = max(1, min(_RECENT_CAP, int(len(samples) * _RECENT_RATIO)))
    if recent is None or recent.maxlen != want:
        # 풀 크기가 바뀌면(어드민이 페어링을 추가) 기억 길이도 다시 맞춘다
        recent = deque(recent or [], maxlen=want)
        _RECENT_SAMPLES[theme] = recent

    fresh = [s for s in samples if s not in used_in_response and s not in recent]
    if not fresh:
        # 다 소진되면 이번 응답 중복만 피한다. 그것도 안 되면 아무거나.
        fresh = [s for s in samples if s not in used_in_response] or samples
    chosen = random.choice(fresh)
    recent.append(chosen)
    return chosen


# ── 테마 선택: 기존 큐레이션에서 학습한 "테마 프로파일" 기반 ──────────
#
# 예전 방식(_theme_candidates_for)은 힌트 키워드를 테마 '이름'에 부분일치시켜
# 첫 매칭을 그대로 채택했다. 세 가지 문제가 있었다:
#   1) usage 축이 사실상 단독으로 테마를 결정 (나머지 4개 축은 死코드)
#   2) meta['usage']가 가나다순이라 "SNS카드"가 항상 먼저 걸림
#      → 전체 폰트의 절반 이상이 '카드뉴스' 테마로 쏠림
#   3) 이름이 긴 복합 테마일수록 키워드가 많이 걸려 유리해짐
#      ("한글 + 영문 조합"은 걸리는 키워드가 0개라 구조적으로 도달 불가)
#
# 대신 이미 어드민이 큐레이션해 둔 페어링에서 테마별 폰트 메타 분포를 학습해
# 프로파일 벡터로 만들고, 후보 폰트쌍과의 코사인 유사도로 테마를 고른다.
# 테마를 새로 추가해도 힌트 테이블을 고칠 필요가 없다.

_META_DIMS = ("usage", "mood", "industry", "personality", "formality")

_HINT_MAPS = {
    "usage": _USAGE_THEME_HINTS,
    "mood": _MOOD_THEME_HINTS,
    "industry": _INDUSTRY_THEME_HINTS,
    "personality": _PERSONALITY_THEME_HINTS,
    "formality": _FORMALITY_THEME_HINTS,
}

# 온도가 낮을수록 유사도 상위 테마에 집중되고, 높을수록 골고루 퍼진다.
# 0.08은 "가장 어울리는 테마 대비 적합도 87%를 유지하면서 1번 슬롯 쏠림을
# 12%까지 낮추는" 지점 — 142개 폰트 전수 시뮬레이션으로 고른 값이다.
_THEME_TEMPERATURE = 0.08
# DB에 이미 많이 쌓인 테마를 얼마나 억제할지 (0이면 억제 없음).
# 너무 크면 최다 노출 테마가 사실상 차단되므로 0.15 정도가 적당하다.
_THEME_BALANCE = 0.15
# 학습 표본이 이보다 적은 테마는 힌트 테이블로 프로파일을 합성해 보완한다.
_MIN_PROFILE_SAMPLES = 3


def _font_features(font: Font) -> Counter:
    """폰트 한 개의 메타/태그를 'dim:value' 피처로 펼친다."""
    c: Counter = Counter()
    meta = font.meta or {}
    for dim in _META_DIMS:
        v = meta.get(dim)
        vals = v if isinstance(v, list) else ([v] if v else [])
        for x in vals:
            c[f"{dim}:{x}"] += 1
    for t in _font_tags(font):
        c[f"tag:{t}"] += 1
    return c


def _hint_profile(theme: str) -> Counter:
    """힌트 테이블을 역방향으로 읽어, 그 테마를 가리키는 메타값들을 프로파일로."""
    c: Counter = Counter()
    for dim, table in _HINT_MAPS.items():
        for value, keywords in table.items():
            if any(kw in theme for kw in keywords):
                c[f"{dim}:{value}"] += 1
    return c


def _l2_tfidf(counts: Counter, idf: dict) -> dict:
    total = sum(counts.values()) or 1
    vec = {k: (n / total) * idf.get(k, 1.0) for k, n in counts.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}


def _cosine(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b[k] for k, v in a.items() if k in b)


def _build_theme_profiles(db: Session, available_themes: list):
    """(테마 → 프로파일 벡터), idf, 테마별 기존 페어링 수를 반환."""
    from ..pairing_phrases import THEME_ALIASES

    raw = {t: Counter() for t in available_themes}
    sample_counts: Counter = Counter()

    for p in db.query(FontPairing).all():
        # 저장된 이름이 옛 표기일 수 있다. 정규화하지 않으면 그 조합들이
        # 프로파일 학습에서 통째로 빠진다(raw 키는 정규명이라 안 걸린다).
        theme = (p.theme or "").strip()
        theme = THEME_ALIASES.get(theme, theme)
        if theme not in raw:
            continue
        for f in (p.title_font, p.body_font):
            if f is not None:
                raw[theme] += _font_features(f)
        sample_counts[theme] += 1

    # 표본이 얇은 테마는 힌트 테이블로 보강 (새로 만든 테마의 콜드스타트 대비)
    for theme in available_themes:
        if sample_counts[theme] < _MIN_PROFILE_SAMPLES:
            for k, v in _hint_profile(theme).items():
                raw[theme][k] += v * 2

    df: Counter = Counter()
    for c in raw.values():
        df.update(c.keys())
    n_themes = max(len(raw), 1)
    idf = {k: math.log(n_themes / (1 + d)) + 1.0 for k, d in df.items()}

    profiles = {t: _l2_tfidf(c, idf) for t, c in raw.items()}
    return profiles, idf, sample_counts


def _pick_theme(title_font: Font, body_font: Font, profiles: dict, idf: dict,
                exposure: Counter, exclude: set) -> str:
    """폰트쌍과 가장 어울리는 테마를 확률적으로 고른다.

    - 유사도가 높을수록 뽑힐 확률이 높지만 결정적이지는 않다(매번 다른 결과).
    - DB에 이미 많이 쌓인 테마는 감점해서, 적게 쓰인 테마도 기회를 갖는다.
    """
    vec = _l2_tfidf(_font_features(title_font) + _font_features(body_font), idf)
    busiest = max(exposure.values()) if exposure else 0

    candidates = []
    for theme, prof in profiles.items():
        if theme in exclude:
            continue
        score = _cosine(vec, prof)
        if busiest:
            score -= _THEME_BALANCE * (exposure.get(theme, 0) / busiest)
        candidates.append((theme, score))
    if not candidates:
        return ""

    lowest = min(s for _, s in candidates)
    weights = [math.exp((s - lowest) / _THEME_TEMPERATURE) for _, s in candidates]
    return random.choices([t for t, _ in candidates], weights=weights, k=1)[0]


# ── 실측 조판 지표 기반 점수 ──────────────────────────────────────
#
# 여기 오기 전까지 점수는 전부 "사람이 손으로 넣은 메타(분위기·용도·업종)와
# 태그"에서만 나왔다. 글자가 실제로 어떻게 생겼는지는 보지 않았다.
# 그래서 조합 145건을 실측값으로 채점해 보면:
#     본문이 제목보다 굵음(역전)   15%
#     굵기 차이가 거의 없음        20%
# 셋 중 하나가 제목과 본문의 위계가 없거나 뒤집혀 있었다. 눈으로 보면 바로
# 이상한데(Bungee는 전체 6번째로 굵은 폰트인데 본문에 앉아 있었다) 메타
# 태그만으로는 걸러낼 수가 없다.
#
# 조판의 원칙은 "굵기는 대비, 비율은 조화"다. 두 항목이 서로 당기게 둔다.

_CONTRAST_LO = 0.12      # 이 아래는 제목/본문 구분이 안 된다
_CONTRAST_HI = 0.45      # 이 위는 과해서 따로 논다


def _contrast(title_font: Font, body_font: Font) -> float:
    """제목이 본문보다 충분히 굵은가. 측정값이 없으면 0(감점 아님)."""
    t = metrics_of(title_font.id)
    b = metrics_of(body_font.id)
    if not t or not b:
        return 0.0
    gap = t[2] - b[2]                      # 채움비율 차이
    if gap < 0:
        # 역전 — 본문이 더 굵다. 위계가 무너지므로 강하게 깎는다.
        return max(-6.0, gap * 20.0)
    if gap < _CONTRAST_LO:
        # 차이가 없어 실수처럼 보인다
        return (gap / _CONTRAST_LO) * 2.0 - 2.0
    if gap <= _CONTRAST_HI:
        return 3.0
    # 과한 대비 — 나쁘진 않지만 최적은 아니다
    return max(0.5, 3.0 - (gap - _CONTRAST_HI) * 6.0)


def _harmony(title_font: Font, body_font: Font) -> float:
    """비율(x-height·글자 폭)이 서로 닮았는가. 측정값이 없으면 0."""
    t = metrics_of(title_font.id)
    b = metrics_of(body_font.id)
    if not t or not b:
        return 0.0
    dx = abs(t[0] - b[0])
    dw = abs(t[1] - b[1]) if t[1] and b[1] else 0.0
    # 0.12 / 0.20을 넘어서면 한 화면에서 크기가 따로 논다
    sx = max(-2.0, 1.5 - (dx / 0.12) * 1.5)
    sw = max(-2.0, 1.5 - (dw / 0.20) * 1.5)
    return sx + sw


def _pick_weight(font: Font, target: int) -> int:
    """폰트가 실제로 가진 굵기 중 target(700=제목용/400=본문용)에 가장 가까운 값."""
    from .files import _merged_weights
    weights = [w["weight"] for w in _merged_weights(font)]
    if not weights:
        return int(font.primary_weight or target)
    return min(weights, key=lambda w: abs(w - target))


def _pick_body_weight(font: Font, title_weight: int) -> int:
    """본문 굵기. 400 고정이 아니라 제목과의 대비를 보고 고른다.

    예전에는 늘 400에 가장 가까운 값을 골라, 굵기를 여러 벌 가진 폰트인데도
    본문이 전부 400으로 나왔다. 제목이 800~900으로 무거운 조합에서는 본문을
    300이나 200으로 낮춰야 위계가 분명해지고, 긴 문장도 덜 답답하다.

    제목이 무거울수록 더 가벼운 본문을 노린다.
      제목 900+ → 300 선호,  800 → 300,  700 → 400,  그 아래 → 400
    폰트가 그 굵기를 실제로 갖고 있지 않으면 가진 것 중 가장 가까운 값이 된다.
    """
    from .files import _merged_weights
    weights = sorted({w["weight"] for w in _merged_weights(font)})
    if not weights:
        return int(font.primary_weight or 400)

    target = 300 if title_weight >= 800 else 400
    # 굵기를 3개 이상 가진 폰트에서는 한 단계 더 가벼운 쪽도 후보로 둔다.
    # 늘 같은 값이 나오면 재생성해도 카드가 똑같아 보인다.
    if len(weights) >= 3 and random.random() < 0.35:
        target = max(200, target - 100)

    body = min(weights, key=lambda w: abs(w - target))
    # 본문이 제목보다 무거우면 위계가 뒤집힌다 — 더 가벼운 값이 있으면 그걸 쓴다.
    if body >= title_weight:
        lighter = [w for w in weights if w < title_weight]
        if lighter:
            body = max(lighter)
    return body


def _describe(title_font: Font, body_font: Font, theme: str) -> str:
    t_summary = (title_font.meta or {}).get("summary") or f"{title_font.name}"
    return (
        f"{theme}에 어울리는 조합이에요. {t_summary}가 제목을 잡고, "
        f"{body_font.name}가 본문을 안정적으로 받쳐줍니다."
    )


class _GenContext:
    """전 폰트에 공통인 준비물. 한 번 만들어 여러 폰트에 재사용한다.

    폰트 하나를 생성할 때마다 다시 만들면(테마 풀 + 프로파일 + 사용횟수)
    FontPairing과 Font를 매번 전수 조회하게 된다. 낱개 호출에서는 문제가
    없지만 전체 재생성처럼 200종을 도는 작업에서는 그것만 200번 반복된다.
    """

    def __init__(self, db: Session):
        self.fonts = [f for f in db.query(Font).all() if not _is_excluded(f)]
        self.theme_pool = _collect_theme_samples(db)
        self.available_themes = list(self.theme_pool.keys())
        self.profiles, self.idf, self.exposure = _build_theme_profiles(
            db, self.available_themes)
        counts: dict = {}
        for (a, b) in db.query(FontPairing.title_font_id, FontPairing.body_font_id).all():
            counts[a] = counts.get(a, 0) + 1
            counts[b] = counts.get(b, 0) + 1
        self.usage_counts = counts


@router.get("/pairings/auto-generate")
def auto_generate_pairings(
    font_id: int,
    top_n: int = 6,
    db: Session = Depends(get_db),
) -> List[dict]:
    """anchor 폰트(font_id)를 기준으로, 전체 폰트 중 메타/태그 궁합이 좋은 상대를 찾아
    제목+본문 조합 후보를 점수순으로 반환한다 (저장은 하지 않음 — 미리보기 전용).

    - A: 카테고리 태그(어드민이 직접 고른 값)를 메타와 함께 매칭에 반영해
      메타가 부실한 폰트도 정당하게 후보에 오르도록 한다.
    - B: 이미 페어링에 많이 쓰인 "단골 폰트"는 노출 점수를 살짝 깎아
      새 폰트가 골고루 추천되게 한다.
    - C: 동점권에서는 매번 다른 조합이 나오도록 약한 무작위 지터를 더한다
      (완전 무작위가 아니라 상위권 내에서만 순서가 흔들리는 정도).
    - D: 태그로 추정한 서체 모양(세리프/산세리프/손글씨/디스플레이) 축을
      제목/본문 적합도와 궁합 점수에 반영한다.
    - E: 테마는 기존 큐레이션에서 학습한 프로파일과의 코사인 유사도로 고르고,
      확률 추출이라 같은 폰트를 다시 조회해도 결과가 달라진다(_pick_theme).
      DB에 이미 많이 쌓인 테마는 감점해 적게 쓰인 테마도 기회를 갖는다.
    - F: 샘플 문구는 DB 문구 + 내장 문구 뱅크를 합친 풀에서 무작위로 뽑는다.
    - G: 실측 조판 지표(대비·조화)를 점수에 반영한다.
    - H: 최근에 이 폰트로 내보낸 파트너는 피한다 — "다른 조합 보기"를 눌렀을 때
      실제로 다른 조합이 나오게 하는 장치다(_RECENT_PARTNERS).

    최소 3개 이상을 목표로 하되, 후보 폰트가 3개 미만이면 있는 만큼만 반환한다.
    """
    anchor = db.query(Font).filter(Font.id == font_id).first()
    if not anchor:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")
    return _generate_for(anchor, _GenContext(db), top_n, avoid_recent=True)


# ── "다른 조합 보기"용 최근 파트너 기억 ─────────────────────────────
#
# 대비·조화 점수를 넣은 뒤로 리롤이 무의미해졌다. 그 두 항목이 결정적이고
# 크기 때문에(+3/−6, +3) 기존 지터(±1.2)로는 순위가 안 흔들린다.
# 실측: 같은 폰트를 4번 조회했더니 1회차와 67~100% 겹치고, 등장한 파트너가
# 8~9종뿐이었다(최대 24종). 사용자가 "같은 조합만 나온다"고 느낀 이유다.
#
# 지터를 키우면 순위가 흔들리지만 나쁜 조합도 같이 올라온다. 대신 최근에
# 보여준 파트너를 피한다 — 점수 순서는 그대로 두고 이미 본 것만 건너뛰므로,
# 리롤하면 "그다음으로 좋은 6개"가 나온다. 자연히 테마와 굵기도 달라져
# 첫 6개와 다른 느낌이 된다.
_RECENT_PARTNERS: dict = {}
_RECENT_PARTNER_CAP = 18     # 6개씩 세 번까지는 안 겹친다


def _generate_for(anchor: Font, ctx: "_GenContext", top_n: int = 6,
                  avoid_recent: bool = False) -> List[dict]:
    """앵커 하나에 대한 조합 후보. 공통 준비물(ctx)은 밖에서 만들어 넘긴다.

    avoid_recent: 최근에 이 앵커로 내보낸 파트너를 피한다("다른 조합 보기"용).
        전체 재생성처럼 폰트마다 한 번씩만 도는 작업에서는 꺼둔다 — 켜두면
        먼저 처리된 폰트가 쓴 파트너를 뒤 폰트가 이유 없이 피하게 된다.
    """
    # 조합에서 완전히 빼는 폰트 (펜시 등) — 앵커 자신이면 결과가 없다.
    if _is_excluded(anchor):
        return []

    anchor_is_english = _is_english_only(anchor)
    candidates = [c for c in ctx.fonts if c.id != anchor.id]
    # 언어 조합 규칙:
    #   한글 앵커 → 한글 상대(일반 조합) + 영문 상대(영문 제목 + 한글 본문)
    #   영문 앵커 → 영문 상대 + 한글 상대(같은 형태를 뒤집은 것)
    # 예전에는 같은 언어권끼리만 붙였는데, 그러면 "한글 + 영문 조합" 테마가
    # 큐레이션에는 있는데 자동 생성으로는 도달할 수 없었다.

    theme_pool = ctx.theme_pool
    available_themes = ctx.available_themes
    theme_profiles, theme_idf, theme_exposure = ctx.profiles, ctx.idf, ctx.exposure

    def _popularity_penalty(fid: int) -> float:
        return min(ctx.usage_counts.get(fid, 0) * 0.6, 4.0)

    JITTER = 1.2  # C: 동점권 다양성용 무작위 폭

    scored = []
    for other in candidates:
        cohesion = _cohesion(anchor, other)
        pen = _popularity_penalty(other.id)
        other_is_english = _is_english_only(other)

        # 조화는 방향과 무관하지만, 대비는 "누가 제목이냐"에 따라 부호가 뒤집힌다.
        harmony = _harmony(anchor, other)

        if other_is_english != anchor_is_english:
            # 언어가 섞인 쌍은 방향이 하나로 정해진다 — 영문이 제목, 한글이 본문.
            # 영문 전용 폰트에 한글 본문을 맡길 수 없고, 문구 뱅크도 그 형태다.
            eng, kor = (anchor, other) if anchor_is_english else (other, anchor)
            score = (
                _title_fit(eng) + _body_fit(kor) + cohesion
                + _contrast(eng, kor) + harmony
                - pen + random.uniform(-JITTER, JITTER)
            )
            scored.append((score, eng, kor))
            continue

        score_a_title = (
            _title_fit(anchor) + _body_fit(other) + cohesion
            + _contrast(anchor, other) + harmony
            - pen + random.uniform(-JITTER, JITTER)
        )
        scored.append((score_a_title, anchor, other))

        score_a_body = (
            _title_fit(other) + _body_fit(anchor) + cohesion
            + _contrast(other, anchor) + harmony
            - pen + random.uniform(-JITTER, JITTER)
        )
        scored.append((score_a_body, other, anchor))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    used_partners = set()
    used_themes = set()      # 이미 배정한 테마 (한 응답 안에서 중복 방지)
    used_samples = set()     # 이미 배정한 (제목,본문) 문구

    recent = None
    if avoid_recent:
        from collections import deque
        recent = _RECENT_PARTNERS.get(anchor.id)
        if recent is None or recent.maxlen != _RECENT_PARTNER_CAP:
            recent = deque(recent or [], maxlen=_RECENT_PARTNER_CAP)
            _RECENT_PARTNERS[anchor.id] = recent

    # 최근 파트너를 피해 한 바퀴 돌고, 그것만으로 top_n을 못 채우면
    # 회피를 풀고 한 바퀴 더 돈다. 후보가 마르면 조용히 예전처럼 동작한다.
    for skip_recent in ((True, False) if recent else (False,)):
        if len(results) >= top_n:
            break
        for score, title_font, body_font in scored:
            if len(results) >= top_n:
                break
            partner = body_font.id if title_font.id == anchor.id else title_font.id
            if partner in used_partners:
                continue
            if skip_recent and recent is not None and partner in recent:
                continue

            # 언어가 섞인 쌍은 테마가 정해져 있다. 이 테마의 문구만 (영문 제목,
            # 한글 본문) 형태라, 다른 테마를 고르면 영문 폰트에 한글 제목이 얹혀
            # 글자가 통째로 깨진다.
            t_eng, b_eng = _is_english_only(title_font), _is_english_only(body_font)
            if t_eng and b_eng:
                # 영문 폰트끼리는 반드시 영문 문구를 써야 한다. 한글 문구가 얹히면
                # 한글 글리프가 없어 화면에서 통째로 깨진다.
                cands = [t for t in _ENGLISH_THEMES if t in theme_pool and t not in used_themes]
                if not cands:
                    cands = [t for t in _ENGLISH_THEMES if t in theme_pool]
                if not cands:
                    continue
                theme = random.choice(cands)
            elif t_eng != b_eng:
                # 그 테마가 없거나 이미 한 장 나갔으면 이 조합은 건너뛴다.
                # 한 응답이 전부 "한글 + 영문 조합"으로 채워지면 탐색이 안 된다.
                if _MIXED_LANG_THEME not in theme_pool or _MIXED_LANG_THEME in used_themes:
                    continue
                theme = _MIXED_LANG_THEME
            else:
                theme = _pick_theme(
                    title_font, body_font, theme_profiles, theme_idf,
                    theme_exposure, used_themes,
                )
                if not theme:
                    theme = next((t for t in available_themes if t not in used_themes), "추천 조합")

            # 문구는 풀에서 무작위로 뽑되, 이번 응답에 이미 쓴 것과
            # 최근 응답들에 나갔던 것을 함께 피한다(_pick_sample).
            samples = theme_pool.get(theme) or [("어울리는 조합을 찾았어요", "제목과 본문에 함께 써보세요")]
            sample_title, sample_body = _pick_sample(theme, samples, used_samples)

            used_partners.add(partner)
            used_themes.add(theme)
            used_samples.add((sample_title, sample_body))
            if recent is not None:
                recent.append(partner)      # 다음 "다른 조합 보기"에서 피할 대상

            tw = _pick_weight(title_font, 700)
            results.append({
                "theme": theme,
                "title_font_id": title_font.id,
                "title_font_name": title_font.name,
                "body_font_id": body_font.id,
                "body_font_name": body_font.name,
                "title_weight": tw,
                "body_weight": _pick_body_weight(body_font, tw),
                "sample_title": sample_title,
                "sample_body": sample_body,
                "description": _describe(title_font, body_font, theme),
                "score": round(score, 1),
                # 카드를 실제 폰트로 그리려면 stack/has_file/available_weights가 필요하다.
                # 위 평면 필드(title_font_id 등)는 어드민 자동생성 모달이 쓰므로 유지한다.
                "title_font": _font_brief(title_font),
                "body_font": _font_brief(body_font),
            })

    return results


@router.post("/pairings/regenerate-all")
def regenerate_all_pairings(
    top_n: int = 6,
    db: Session = Depends(get_db),
    _admin = Depends(require_password_changed),
):
    """전체 폰트의 추천 조합을 지금 알고리즘으로 다시 만들어 통째로 교체한다.

    ⚠️ 순서가 중요하다: **먼저 전부 생성하고, 그 다음에 지운다.**
    생성기는 기존 페어링에서 테마를 학습한다(_collect_theme_samples,
    _build_theme_profiles). 지우고 시작하면 테마 풀이 비어서 결과가 전부
    "추천 조합" 하나에 같은 문구로 나온다.

    공통 준비물(_GenContext)은 한 번만 만든다. 폰트마다 다시 만들면
    FontPairing·Font 전수 조회를 폰트 수만큼 반복하게 된다.
    """
    ctx = _GenContext(db)
    fonts = sorted(ctx.fonts, key=lambda f: f.id)

    # ① 생성 (아직 DB는 건드리지 않는다)
    rows = []
    for f in fonts:
        for p in _generate_for(f, ctx, top_n):
            rows.append(p)

    if not rows:
        raise HTTPException(status_code=500, detail="생성 결과가 없어 교체하지 않았습니다")

    # ② 교체 — 한 트랜잭션에서. 실패하면 통째로 롤백되어 기존 데이터가 남는다.
    removed = db.query(FontPairing).delete()
    for i, p in enumerate(rows):
        db.add(FontPairing(
            theme=p["theme"],
            title_font_id=p["title_font_id"],
            body_font_id=p["body_font_id"],
            sample_title=p["sample_title"],
            sample_body=p["sample_body"],
            description=p["description"],
            title_weight=p["title_weight"],
            body_weight=p["body_weight"],
            sort_order=(i + 1) * 10,
        ))
    db.commit()

    themes: dict = {}
    for p in rows:
        themes[p["theme"]] = themes.get(p["theme"], 0) + 1
    print(f"[pairings] 전체 재생성: {removed}건 삭제 → {len(rows)}건 생성")
    return {
        "removed": removed,
        "created": len(rows),
        "fonts": len(fonts),
        "themes": dict(sorted(themes.items(), key=lambda kv: -kv[1])),
    }


# ═══════════════════════════════════════════════════════════════════
# 조합 페이지(/font-pair) 전용 — 3슬롯 즉석 생성
# ═══════════════════════════════════════════════════════════════════
#
# 위의 auto-generate와 무엇이 다른가
# ---------------------------------
# · auto-generate는 앵커 폰트 하나에 대한 **2폰트 조합 여러 벌**을 준다.
#   여기는 **3폰트 한 벌**(타이틀·서브타이틀·본문)을 준다.
# · auto-generate는 theme 파라미터를 받지 않는다. 여기는 카테고리를 실제로
#   반영한다 — 카테고리 선택이 이 페이지의 핵심 기능이다.
# · 슬롯을 잠글 수 있다. 잠긴 것은 그대로 두고 나머지만 다시 뽑는다.
#
# FontPairing 테이블은 건드리지 않는다. 저장하지 않는 읽기 전용 생성이라
# 2폰트 구조인 스키마를 늘릴 이유가 없다.

from ..pair_specimens import (
    PAIR_CATEGORIES as _PAIR_CATEGORIES,
    SURPRISE_CATEGORY as _SURPRISE,
    get_category as _get_category,
    themes_of as _themes_of,
    specimen as _specimen,
)

_CATEGORY_POOL = 60      # 카테고리 친화도 상위 몇 종을 후보로 둘 것인가


def _category_pool(ctx: "_GenContext", category: str, fonts: list) -> list:
    """카테고리와 어울리는 폰트만 남긴다.

    테마 프로파일(_build_theme_profiles)과의 코사인 유사도를 쓴다. 카테고리가
    묶는 테마가 여럿이므로 그중 가장 높은 값을 그 폰트의 점수로 본다.
    '뜻밖의 발견'은 이 걸러내기를 통째로 건너뛴다 — 어울림 계산을 끄는 것이
    그 카테고리의 존재 이유다.
    """
    themes = _themes_of(category)
    if not themes:
        return list(fonts)
    profs = [ctx.profiles[t] for t in themes if t in ctx.profiles]
    if not profs:
        return list(fonts)

    scored = []
    for f in fonts:
        vec = _l2_tfidf(_font_features(f), ctx.idf)
        scored.append((max(_cosine(vec, p) for p in profs), f))
    scored.sort(key=lambda x: x[0], reverse=True)
    pool = [f for _, f in scored[:_CATEGORY_POOL]]
    # 후보가 너무 적으면(태그가 부실한 카테고리) 전체로 되돌린다. 세 슬롯을
    # 못 채우느니 카테고리를 느슨하게 보는 편이 낫다.
    return pool if len(pool) >= 12 else list(fonts)


def _eng_for_pair(font: "Font") -> bool:
    """이 폰트에 한글을 얹으면 깨지는가.

    _is_english_only는 태그(_ENGLISH_ONLY_TAGS)만 본다. 그런데 태그가 '본문용
    영어'인 폰트들(LibreBodoni·Montserrat·OpenSans·Playfair Display·Roboto)은
    그 집합에 없어서 한글 폰트로 분류된다. 실측으로 5종이 어긋났다.
    Font.is_english 컬럼이 프론트가 쓰는 값이자 더 정확하므로 둘을 합쳐 본다.

    _is_english_only 자체는 고치지 않는다 — 저장된 조합을 만드는 auto-generate가
    그 판별에 맞춰 동작하고 있어, 건드리면 그쪽 결과가 함께 바뀐다.
    """
    return bool(getattr(font, "is_english", False)) or _is_english_only(font)


def _script_pools(script: str, fonts: list) -> tuple:
    """스크립트 규칙에 맞는 (제목 후보, 서브·본문 후보).

    영문 전용 폰트에 한글 문구를 얹으면 글리프가 없어 통째로 깨진다. 그래서
    후보를 나누는 기준은 취향이 아니라 '그 문구가 그려지는가'다.
    mix는 pair_specimens.specimen()의 mix와 같은 배치여야 한다 —
    제목만 영문, 서브·본문은 한글.
    """
    eng = [f for f in fonts if _eng_for_pair(f)]
    kor = [f for f in fonts if not _eng_for_pair(f)]
    if script == "en":
        return eng, eng
    if script == "mix":
        return eng, kor
    return kor, kor


def _cap_weight(font: "Font", target: int, cap: int) -> int:
    """target에 가장 가까운 굵기를 고르되 cap을 넘지 않는다.

    _pick_weight은 그 폰트가 가진 굵기 중 target에 가장 가까운 값을 준다. 그래서
    무거운 굵기만 가진 폰트가 서브타이틀에 앉으면 제목보다 굵어진다 — 운영에서
    400/800/400(서브가 제목보다 무거움)이 실제로 나왔다. 위계가 뒤집히면 어느
    쪽이 제목인지 화면에서 읽히지 않는다.

    cap 이하인 굵기가 하나도 없으면 어쩔 수 없이 가진 것 중에서 고른다.
    그런 폰트를 아예 배제하면 후보가 크게 줄고, 크기 차이가 이미 위계를
    만들어 주므로(제목 60px · 본문 16.5px) 그 정도는 견딜 만하다.
    """
    from .files import _merged_weights
    ws = [w["weight"] for w in _merged_weights(font)] or [int(font.primary_weight or target)]
    pool = [w for w in ws if w <= cap] or ws
    return min(pool, key=lambda w: abs(w - target))


def _pick_one(pool: list, used: set, key=None):
    """후보에서 하나 고른다. 이미 쓴 폰트는 뺀다 — 세 슬롯이 겹치지 않는 근거."""
    avail = [f for f in pool if f.id not in used]
    if not avail:
        return None
    if key is None:
        return random.choice(avail)
    # 상위권에서 무작위로 — 늘 1등만 나오면 새로 뽑아도 그대로다.
    ranked = sorted(avail, key=key, reverse=True)
    return random.choice(ranked[:max(3, len(ranked) // 4)])


@router.get("/font-pair/generate")
def font_pair_generate(
    category: str = "brand",
    script: str = "ko",
    title: int = 0,
    subtitle: int = 0,
    body: int = 0,
    db: Session = Depends(get_db),
):
    """타이틀·서브타이틀·본문 3폰트 한 벌. 0이 아닌 슬롯은 잠긴 것으로 본다."""
    if script not in ("ko", "en", "mix"):
        script = "ko"
    cat = _get_category(category)
    ctx = _GenContext(db)

    by_id = {f.id: f for f in ctx.fonts}
    surprise = cat["key"] == _SURPRISE

    pool = ctx.fonts if surprise else _category_pool(ctx, cat["key"], ctx.fonts)
    title_pool, text_pool = _script_pools(script, pool)
    # 스크립트로 좁혔더니 비었다면 카테고리 쪽을 포기한다(스크립트는 못 어긴다).
    if len(title_pool) < 1 or len(text_pool) < 2:
        title_pool, text_pool = _script_pools(script, ctx.fonts)

    used = set()
    locked = {}
    for slot, fid in (("title", title), ("subtitle", subtitle), ("body", body)):
        f = by_id.get(fid or 0)
        if f is not None:
            locked[slot] = f
            used.add(f.id)

    t_font = locked.get("title") or _pick_one(
        title_pool, used, None if surprise else (lambda f: _title_fit(f)))
    if t_font is None:
        raise HTTPException(status_code=503, detail="제목 후보를 찾지 못했습니다")
    used.add(t_font.id)

    b_font = locked.get("body") or _pick_one(
        text_pool, used,
        None if surprise else (lambda f: _body_fit(f) + _cohesion(t_font, f)
                               + _contrast(t_font, f) + _harmony(t_font, f)))
    if b_font is None:
        raise HTTPException(status_code=503, detail="본문 후보를 찾지 못했습니다")
    used.add(b_font.id)

    # 서브타이틀은 제목과 본문 사이에 놓인다. 셋이 전부 다른 계열이면 견본이
    # 산만해지므로, 이미 뽑힌 둘과 결이 닮은 쪽을 우선한다(_cohesion).
    s_font = locked.get("subtitle") or _pick_one(
        text_pool, used,
        None if surprise else (lambda f: _cohesion(t_font, f) + _cohesion(b_font, f)))
    if s_font is None:
        # 후보가 말랐다 — 스크립트만 지키고 전체에서 다시 찾는다.
        _, wide = _script_pools(script, ctx.fonts)
        s_font = _pick_one(wide, used)
    if s_font is None:
        raise HTTPException(status_code=503, detail="서브타이틀 후보를 찾지 못했습니다")

    t_w = _pick_weight(t_font, 700)
    b_w = _cap_weight(b_font, _pick_body_weight(b_font, t_w), t_w)
    # 서브타이틀은 제목보다 가볍고 본문보다 무겁거나 같게 — 위계가 셋으로 보인다.
    s_w = _cap_weight(s_font, max(b_w, min(t_w, 500)), t_w)

    return {
        "category": cat["key"],
        "category_label": cat["label"],
        "script": script,
        "fonts": {
            "title": _font_brief(t_font),
            "subtitle": _font_brief(s_font),
            "body": _font_brief(b_font),
        },
        "weights": {"title": t_w, "subtitle": s_w, "body": b_w},
        "samples": _specimen(cat["key"], script),
    }


@router.get("/font-pair/categories")
def font_pair_categories():
    """카테고리 칩 목록. 화면이 이름을 따로 갖고 있지 않게 서버가 준다."""
    return [{"key": c["key"], "label": c["label"]} for c in _PAIR_CATEGORIES]
