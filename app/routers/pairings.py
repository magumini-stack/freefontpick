"""폰트 페어링 API

- GET /api/pairings                 : 전체 페어링 (테마별 정렬) — 공개
- GET /api/fonts/{font_id}/pairings : 특정 폰트가 포함된 페어링 — 공개
- GET /api/pairings/themes          : 전체 테마 이름 목록 — 공개 (어드민 드롭다운용)
- POST /api/pairings                : 페어링 생성 — 관리자
- PATCH /api/pairings/{id}          : 페어링 수정 — 관리자
- DELETE /api/pairings/{id}         : 페어링 삭제 — 관리자
"""
import random
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


def _to_out(p: FontPairing) -> dict:
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
    return [_to_out(p) for p in rows]


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
    return [_to_out(p) for p in rows]


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


# 카테고리 태그가 제목/본문 어느 쪽에 더 잘 맞는지에 대한 힌트.
# 메타(무드/용도 등)가 부실해도 어드민이 직접 고른 태그는 대체로 신뢰도가 높다.
_TAG_TITLE_HINTS = {
    "시선을 끄는 제목용", "유튜브 썸네일 추천", "로고디자인", "독특한",
    "캘리그라피", "펜시", "귀여운", "꽉찬고딕",
}
_TAG_BODY_HINTS = {
    "가독성 좋은 고딕", "정보전달 본문용", "UI/UX/Web", "부드러운 명조",
    "부드러운 굴림", "또박또박 손글씨", "카드뉴스용",
}

# 태그로부터 대략적인 서체 모양(세리프/산세리프/손글씨/디스플레이)을 추정.
# 같은 모양끼리는 톤이 자연스럽게 어울리고, display 계열은 제목에, serif/sans는
# 본문 가독성에 강점이 있다는 일반적인 타이포그래피 관행을 반영한다.
_SHAPE_TAG_MAP = {
    "부드러운 명조": "serif",
    "가독성 좋은 고딕": "sans", "꽉찬고딕": "sans", "부드러운 굴림": "sans", "UI/UX/Web": "sans",
    "또박또박 손글씨": "script", "캘리그라피": "script", "펜시": "script", "귀여운": "script",
    "시선을 끄는 제목용": "display", "유튜브 썸네일 추천": "display", "로고디자인": "display",
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
    """DB의 기존 페어링에서 (테마 → [(제목문구, 본문문구), ...]) 수집.

    자동 생성 후보에 실제로 쓰인 다양한 문구를 배정하기 위한 소스.
    비어있으면 최소한의 기본값 하나를 반환한다.
    """
    pool: dict = {}
    rows = db.query(FontPairing).all()
    for p in rows:
        theme = (p.theme or "").strip()
        if not theme:
            continue
        st = (p.sample_title or "").strip()
        sb = (p.sample_body or "").strip()
        if not st and not sb:
            continue
        pool.setdefault(theme, [])
        if (st, sb) not in pool[theme]:
            pool[theme].append((st, sb))
    if not pool:
        pool["추천 조합"] = [("어울리는 조합을 찾았어요", "제목과 본문에 함께 써보세요")]
    return pool


def _theme_candidates_for(meta_a: dict, meta_b: dict, available_themes: list) -> list:
    """두 폰트의 usage/mood를 근거로, 실제 등록된 테마 중 어울리는 것들을
    우선순위 순으로 반환한다. 하나도 못 맞추면 전체 테마를 반환(폴백)."""
    hints = []
    for u in (meta_a.get("usage") or []) + (meta_b.get("usage") or []):
        hints += _USAGE_THEME_HINTS.get(u, [])
    for mood in (meta_a.get("mood") or []) + (meta_b.get("mood") or []):
        hints += _MOOD_THEME_HINTS.get(mood, [])

    matched, seen = [], set()
    for kw in hints:
        for theme in available_themes:
            if kw in theme and theme not in seen:
                matched.append(theme)
                seen.add(theme)
    # 매칭된 것 뒤에 나머지 테마도 폴백으로 이어붙임
    for theme in available_themes:
        if theme not in seen:
            matched.append(theme)
    return matched


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

    테마와 샘플 문구는 DB에 이미 등록된 페어링들에서 수집한 풀에서 뽑아,
    후보마다 서로 다른 테마·문구가 배정되도록 한다(중복 최소화).
    최소 3개 이상을 목표로 하되, 후보 폰트가 3개 미만이면 있는 만큼만 반환한다.
    """
    anchor = db.query(Font).filter(Font.id == font_id).first()
    if not anchor:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    candidates = db.query(Font).filter(Font.id != font_id).all()

    theme_pool = _collect_theme_samples(db)
    available_themes = list(theme_pool.keys())

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
    used_themes = set()      # 이미 배정한 테마 (다양성 확보)
    used_samples = set()     # 이미 배정한 (제목,본문) 문구
    theme_sample_idx = {}    # 테마별로 다음에 꺼낼 문구 인덱스

    for score, title_font, body_font in scored:
        partner = body_font.id if title_font.id == anchor.id else title_font.id
        if partner in used_partners:
            continue

        theme_order = _theme_candidates_for(
            title_font.meta or {}, body_font.meta or {}, available_themes,
        )
        # 아직 안 쓴 테마를 우선 배정 (다양성), 다 썼으면 순서대로
        theme = next((t for t in theme_order if t not in used_themes), theme_order[0] if theme_order else "추천 조합")

        samples = theme_pool.get(theme) or [("어울리는 조합을 찾았어요", "제목과 본문에 함께 써보세요")]
        idx = theme_sample_idx.get(theme, 0)
        sample_title, sample_body = samples[idx % len(samples)]
        # 같은 문구가 이미 쓰였으면 다음 문구로 회피
        tries = 0
        while (sample_title, sample_body) in used_samples and tries < len(samples):
            idx += 1
            sample_title, sample_body = samples[idx % len(samples)]
            tries += 1
        theme_sample_idx[theme] = idx + 1

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
