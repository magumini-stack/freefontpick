"""폰트 페어링 API

- GET /api/pairings                 : 전체 페어링 (테마별 정렬) — 공개
- GET /api/fonts/{font_id}/pairings : 특정 폰트가 포함된 페어링 — 공개
- GET /api/pairings/themes          : 전체 테마 이름 목록 — 공개 (어드민 드롭다운용)
- POST /api/pairings                : 페어링 생성 — 관리자
- PATCH /api/pairings/{id}          : 페어링 수정 — 관리자
- DELETE /api/pairings/{id}         : 페어링 삭제 — 관리자
"""
import math
import random
from collections import Counter
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Font, FontPairing
from ..auth import require_password_changed
from ..schemas import PairingCreate, PairingUpdate

router = APIRouter(prefix="/api", tags=["pairings"])


def _font_brief(f: Font) -> dict:
    from .files import _merged_weights
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
    from .files import FONT_AUDIT, FONT_RESOLUTION, WEIGHT_RESOLUTION, WEIGHT_UNMATCHED, build_font_resolution
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
    """
    from ..pairing_phrases import THEME_PHRASE_BANK, THEME_ALIASES

    pool: dict = {}

    def _add(theme: str, st: str, sb: str):
        if not theme or (not st and not sb):
            return
        bucket = pool.setdefault(theme, [])
        if (st, sb) not in bucket:
            bucket.append((st, sb))

    for p in db.query(FontPairing).all():
        _add((p.theme or "").strip(),
             (p.sample_title or "").strip(),
             (p.sample_body or "").strip())

    # 뱅크 병합 — DB에 존재하는 테마에만 붙인다(쓰이지 않는 테마를 새로 만들지 않음).
    # 파편화된 테마명("SNS 카드뉴스" 등)은 정규 테마의 뱅크를 함께 쓴다.
    for theme in list(pool.keys()):
        canon = THEME_ALIASES.get(theme, theme)
        for st, sb in THEME_PHRASE_BANK.get(canon, []):
            _add(theme, st, sb)

    if not pool:
        pool["추천 조합"] = [("어울리는 조합을 찾았어요", "제목과 본문에 함께 써보세요")]
    return pool


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
    raw = {t: Counter() for t in available_themes}
    sample_counts: Counter = Counter()

    for p in db.query(FontPairing).all():
        theme = (p.theme or "").strip()
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


def _pick_weight(font: Font, target: int) -> int:
    """폰트가 실제로 가진 굵기 중 target(700=제목용/400=본문용)에 가장 가까운 값."""
    from .files import _merged_weights
    weights = [w["weight"] for w in _merged_weights(font)]
    if not weights:
        return int(font.primary_weight or target)
    return min(weights, key=lambda w: abs(w - target))


def _describe(title_font: Font, body_font: Font, theme: str) -> str:
    t_summary = (title_font.meta or {}).get("summary") or f"{title_font.name}"
    return (
        f"{theme}에 어울리는 조합이에요. {t_summary}가 제목을 잡고, "
        f"{body_font.name}가 본문을 안정적으로 받쳐줍니다."
    )


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

    최소 3개 이상을 목표로 하되, 후보 폰트가 3개 미만이면 있는 만큼만 반환한다.
    """
    anchor = db.query(Font).filter(Font.id == font_id).first()
    if not anchor:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    # 언어 필터: 한글 폰트끼리, 영문 폰트끼리만 페어링
    anchor_is_english = _is_english_only(anchor)
    candidates = db.query(Font).filter(Font.id != font_id).all()
    candidates = [c for c in candidates if _is_english_only(c) == anchor_is_english]

    theme_pool = _collect_theme_samples(db)
    available_themes = list(theme_pool.keys())
    theme_profiles, theme_idf, theme_exposure = _build_theme_profiles(db, available_themes)

    # B: 폰트별 기존 페어링 등장 횟수 (단골 폰트 노출 억제용)
    usage_counts: dict = {}
    for (a, b) in db.query(FontPairing.title_font_id, FontPairing.body_font_id).all():
        usage_counts[a] = usage_counts.get(a, 0) + 1
        usage_counts[b] = usage_counts.get(b, 0) + 1

    def _popularity_penalty(fid: int) -> float:
        return min(usage_counts.get(fid, 0) * 0.6, 4.0)

    JITTER = 1.2  # C: 동점권 다양성용 무작위 폭

    scored = []
    for other in candidates:
        cohesion = _cohesion(anchor, other)
        pen = _popularity_penalty(other.id)

        score_a_title = (
            _title_fit(anchor) + _body_fit(other) + cohesion
            - pen + random.uniform(-JITTER, JITTER)
        )
        scored.append((score_a_title, anchor, other))

        score_a_body = (
            _title_fit(other) + _body_fit(anchor) + cohesion
            - pen + random.uniform(-JITTER, JITTER)
        )
        scored.append((score_a_body, other, anchor))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    used_partners = set()
    used_themes = set()      # 이미 배정한 테마 (한 응답 안에서 중복 방지)
    used_samples = set()     # 이미 배정한 (제목,본문) 문구

    for score, title_font, body_font in scored:
        partner = body_font.id if title_font.id == anchor.id else title_font.id
        if partner in used_partners:
            continue

        theme = _pick_theme(
            title_font, body_font, theme_profiles, theme_idf,
            theme_exposure, used_themes,
        )
        if not theme:
            theme = next((t for t in available_themes if t not in used_themes), "추천 조합")

        # 문구는 풀에서 무작위로 뽑는다. 예전에는 인덱스 0부터 순서대로 꺼냈는데,
        # 인덱스가 요청마다 초기화돼서 테마별로 늘 같은 문구만 나왔다.
        samples = theme_pool.get(theme) or [("어울리는 조합을 찾았어요", "제목과 본문에 함께 써보세요")]
        sample_title, sample_body = random.choice(samples)
        tries = 0
        while (sample_title, sample_body) in used_samples and tries < len(samples):
            sample_title, sample_body = random.choice(samples)
            tries += 1

        used_partners.add(partner)
        used_themes.add(theme)
        used_samples.add((sample_title, sample_body))

        results.append({
            "theme": theme,
            "title_font_id": title_font.id,
            "title_font_name": title_font.name,
            "body_font_id": body_font.id,
            "body_font_name": body_font.name,
            "title_weight": _pick_weight(title_font, 700),
            "body_weight": _pick_weight(body_font, 400),
            "sample_title": sample_title,
            "sample_body": sample_body,
            "description": _describe(title_font, body_font, theme),
            "score": round(score, 1),
        })
        if len(results) >= top_n:
            break

    return results
