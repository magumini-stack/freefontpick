"""DB 초기화 + 142개 폰트 시드 데이터 삽입

앱 시작 시 한 번 실행됨:
1. DB 테이블 생성 (없으면)
2. admin 계정이 없으면 기본 계정 생성 (admin / 임시비번 / must_change_password=True)
3. 카테고리/폰트가 비어있으면 seed_data.json에서 142개 일괄 삽입

폰트 파일은 static/fonts/ 폴더에 묶여있어 별도 복사 없이 그대로 서빙됨.
어드민에서 업로드하면 /app/user_data/fonts/ 에 저장되어 우선 적용됨.
"""
import json
import os
from pathlib import Path
from sqlalchemy.orm import Session

from .database import engine, SessionLocal, Base
from .models import Font, Tag, AdminUser, FontPairing, AppMeta
from .auth import hash_password


SEED_PATH = Path(__file__).resolve().parent.parent / "seed_data.json"
BUNDLED_FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"

DEFAULT_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
# 첫 로그인용 임시 비밀번호 — must_change_password=True로 시작
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_INITIAL_PASSWORD", "freefontpick2026!")


def init_db():
    """테이블 생성 + 시드 데이터 (가벼움 — 폰트 파일 복사 없음)"""
    Base.metadata.create_all(bind=engine)
    _ensure_like_count_column()
    _ensure_pairing_weight_columns()
    _ensure_primary_weight_column()
    _ensure_webfont_columns()
    _ensure_is_pick_column()
    _ensure_tag_axis_column()
    _ensure_use_case_tips_column()
    db = SessionLocal()
    try:
        _seed_admin(db)
        _seed_fonts_and_tags(db)
        _migrate_tag_axes(db)
        _seed_pairings(db)
        _seed_use_cases(db)
        _migrate_impact_hub(db)
        _seed_gif_use_cases(db)
        _seed_gif_templates(db)
        # 폰트 파일 이름 기반 해석 + has_file/stack 자가치유
        from .routers.files import build_font_resolution
        build_font_resolution(db)
    finally:
        db.close()


def _ensure_like_count_column():
    """기존 fonts 테이블에 like_count 컬럼이 없으면 추가 (마이그레이션 보조).

    SQLAlchemy create_all은 이미 있는 테이블에 컬럼을 추가하지 않는다.
    운영 환경에서 모델 변경 후 안전하게 컬럼을 추가하기 위한 보조 함수.
    """
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    if "fonts" not in inspector.get_table_names():
        return  # create_all이 이번에 만들었음
    columns = {col["name"] for col in inspector.get_columns("fonts")}
    if "like_count" in columns:
        return  # 이미 있음
    # MySQL/SQLite 둘 다 호환되는 ALTER 문
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE fonts ADD COLUMN like_count INTEGER NOT NULL DEFAULT 0"))
    print("[migrate] fonts.like_count 컬럼 추가 완료")


def _ensure_pairing_weight_columns():
    """font_pairings 테이블에 title_weight/body_weight 컬럼이 없으면 추가.

    v5 페어링에서 조합별 굵기 지정을 위해 도입.
    """
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    if "font_pairings" not in inspector.get_table_names():
        return  # create_all이 이번에 만들었음
    columns = {col["name"] for col in inspector.get_columns("font_pairings")}
    added = []
    with engine.begin() as conn:
        if "title_weight" not in columns:
            conn.execute(text("ALTER TABLE font_pairings ADD COLUMN title_weight INTEGER NOT NULL DEFAULT 700"))
            added.append("title_weight")
        if "body_weight" not in columns:
            conn.execute(text("ALTER TABLE font_pairings ADD COLUMN body_weight INTEGER NOT NULL DEFAULT 400"))
            added.append("body_weight")
    if added:
        print(f"[migrate] font_pairings 컬럼 추가 완료: {added}")


def _ensure_primary_weight_column():
    """fonts 테이블에 primary_weight 컬럼이 없으면 추가.

    어드민 굵기 등록 기능(대표 굵기 지정) 도입을 위해 필요.
    기본값 400(Regular)으로 채워 기존 데이터 호환성 유지.
    """
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    if "fonts" not in inspector.get_table_names():
        return  # create_all이 이번에 만들었음
    columns = {col["name"] for col in inspector.get_columns("fonts")}
    if "primary_weight" in columns:
        return  # 이미 있음
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE fonts ADD COLUMN primary_weight INTEGER NOT NULL DEFAULT 400"))
    print("[migrate] fonts.primary_weight 컬럼 추가 완료")


def _ensure_webfont_columns():
    """fonts 테이블에 webfont_family/webfont_css_url/webfont_weights 컬럼이 없으면 추가.

    Google Fonts 등 CDN 웹폰트를 파일 업로드 없이 등록하는 기능을 위해 필요.
    """
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    if "fonts" not in inspector.get_table_names():
        return  # create_all이 이번에 만들었음
    columns = {col["name"] for col in inspector.get_columns("fonts")}
    added = []
    with engine.begin() as conn:
        if "webfont_family" not in columns:
            conn.execute(text("ALTER TABLE fonts ADD COLUMN webfont_family VARCHAR(200) NULL"))
            added.append("webfont_family")
        if "webfont_css_url" not in columns:
            conn.execute(text("ALTER TABLE fonts ADD COLUMN webfont_css_url VARCHAR(500) NULL"))
            added.append("webfont_css_url")
        if "webfont_weights" not in columns:
            conn.execute(text("ALTER TABLE fonts ADD COLUMN webfont_weights VARCHAR(100) NULL"))
            added.append("webfont_weights")
    if added:
        print(f"[migrate] fonts 웹폰트 컬럼 추가 완료: {added}")


def _ensure_is_pick_column():
    """fonts 테이블에 is_pick 컬럼이 없으면 추가.

    메인 페이지 "큐레이터 픽" 섹션 — 어드민이 체크박스로 지정한 추천 폰트를 노출하기 위해 필요.
    (2026-08 홈 리디자인에서 화면 노출은 걷어냈지만, 컬럼과 어드민 체크박스는 유지한다.)
    """
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    if "fonts" not in inspector.get_table_names():
        return  # create_all이 이번에 만들었음
    columns = {col["name"] for col in inspector.get_columns("fonts")}
    if "is_pick" in columns:
        return  # 이미 있음
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE fonts ADD COLUMN is_pick BOOLEAN NOT NULL DEFAULT 0"))
    print("[migrate] fonts.is_pick 컬럼 추가 완료")


def _ensure_use_case_tips_column():
    """use_cases 테이블에 tips 컬럼이 없으면 추가.

    활용 방법을 한 문단에서 [라벨, 내용] 3단 구조로 바꾸기 위해 필요.
    """
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    if "use_cases" not in inspector.get_table_names():
        return  # create_all이 이번에 만들었음
    columns = {col["name"] for col in inspector.get_columns("use_cases")}
    if "tips" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE use_cases ADD COLUMN tips JSON NULL"))
    print("[migrate] use_cases.tips 컬럼 추가 완료")


def _ensure_tag_axis_column():
    """tags 테이블에 axis 컬럼('use'|'shape'|'mood')이 없으면 추가.

    태그 3축 분리(용도/모양/느낌)의 기반 — 레일 필터는 shape만, 용도 허브는 use만 쓰게 된다.
    """
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    if "tags" not in inspector.get_table_names():
        return  # create_all이 이번에 만들었음
    columns = {col["name"] for col in inspector.get_columns("tags")}
    if "axis" in columns:
        return  # 이미 있음
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tags ADD COLUMN axis VARCHAR(10) NULL"))
    print("[migrate] tags.axis 컬럼 추가 완료")


# ── 태그 정리 마이그레이션 데이터 (2026-08 태그 3축 분리) ─────────────────
# 구 태그명 → 신 태그명. 신 태그가 이미 있으면 병합(폰트 연결 이전 후 구 태그 삭제).
_TAG_RENAMES = {
    "또박또박 손글씨": "손글씨",
    # 아래 4건은 운영 DB에선 이미 어드민에서 이관 완료 — 신규 설치(seed) 경로 대비용
    "가독성 좋은 고딕": "제목-본문용 고딕",
    "꽉찬고딕": "네모틀 고딕",
    "부드러운 명조": "부드러운 바탕",
    "부드러운 굴림": "제목용 굴림",
}

# 태그명 → 축. 여기 없는 태그(향후 어드민 신규 생성 등)는 NULL 유지.
_TAG_AXIS = {
    # use: 용도 허브로 승격 예정
    "유튜브 썸네일 추천": "use", "브이로그 자막용": "use", "카드뉴스용": "use",
    "UI/UX/Web": "use", "로고디자인": "use", "시선을 끄는 제목용": "use",
    # shape: 레일 필터 유지
    "제목-본문용 고딕": "shape", "네모틀 고딕": "shape", "제목용 굴림": "shape",
    "부드러운 바탕": "shape", "독특한 세리프": "shape", "디스플레이": "shape",
    "장식": "shape", "손글씨": "shape", "캘리그라피": "shape", "펜시": "shape",
    "디자인 영어": "shape", "본문용 영어": "shape",
    # 실서버에서 '본문용 영어' → '디자이너 필수 영문'으로 개명된 상태 반영
    "디자이너 필수 영문": "shape",
    # mood: 추천 매칭 축
    "귀여운": "mood",
}

# 모양(shape) 태그가 하나도 없는 폰트 보완 — 2026-08 실서버 전수 확인분.
_SHAPE_BACKFILL = {
    "구름산스": "제목-본문용 고딕",
    "KoPub돋움": "제목-본문용 고딕",
    "메모먼트 꾹꾹체": "손글씨",
    "카페 24 빛나는별": "손글씨",
    "창원단감아삭체": "디스플레이",
    "넥슨 배찌체": "손글씨",
    "메이플스토리": "손글씨",
    "쿠키런": "제목용 굴림",
    "수박양체": "손글씨",
    "온글잎 박다현체": "손글씨",
    "카페24 고운밤": "손글씨",
    "핑크퐁 아기상어체": "손글씨",
    "카페24 슈퍼매직": "손글씨",
    "제주 돌담체": "손글씨",
}


TAG_AXIS_MIGRATION_KEY = "tag_axis_migrated"


# ═══════════════════════════════════════════════════════════
# 청첩장 허브 → '임팩트가 필요할 때!' 교체 (2026-08, 일회성)
# ═══════════════════════════════════════════════════════════
IMPACT_HUB_MIGRATION_KEY = "impact_hub_migration_v1"

# 상위픽은 썸네일 허브(여기어때 잘난체·검은고딕·열정도체·SB어그로체)와
# 일부러 겹치지 않게 골랐다. 상위 4종이 3개 이상 겹치면 사용자에게는
# 두 허브가 같은 페이지로 보인다 (use_case_data.py 상단 주석 참조).
_IMPACT_PICKS = [
    (71, "원스토어 모바일고딕 제목체",
     "네모틀을 꽉 채우는 제목체라 한 단어만 얹어도 화면을 장악합니다."),
    (76, "이사만루체",
     "획이 두껍고 각이 살아 있어 스포츠·이벤트처럼 기세가 필요한 자리에 맞습니다."),
    (96, "태나다체",
     "굵기에 개성이 얹혀 있어 비슷비슷한 굵은 제목들 사이에서 구분됩니다."),
    (41, "배달의민족 을지로체",
     "간판 글씨에서 온 서체라 레트로한 강조가 필요할 때 분위기까지 같이 잡힙니다."),
]

_IMPACT_PHRASES = [
    "지금 아니면 안 돼",
    "단 하루, 오늘만",
    "이건 진짜 봐야 합니다",
    "올해 마지막 기회입니다",
]

_IMPACT_TIPS = [
    ["크기·굵기", "본문의 2.5배 이상. 임팩트는 굵기가 아니라 '본문과의 차이'에서 나옵니다."],
    ["글자 수", "한 줄 8자 이내. 길어지면 강조가 아니라 그냥 큰 글씨가 됩니다."],
    ["주의", "한 화면에 강조는 하나만. 둘 이상이면 서로 힘을 깎아먹습니다."],
]


def _migrate_impact_hub(db: Session):
    """청첩장 허브를 감추고 '임팩트가 필요할 때!' 허브를 그 자리에 만든다.

    ⚠ 시드 재실행이 아니라 해당 행만 손대는 일회성 작업이다.
    어드민에서 편집한 다른 허브는 건드리지 않는다 (use_case_admin_edited
    플래그 때문에 시드는 이미 통째로 건너뛰는 상태다).

    app_meta에 표시해 두 번 실행되지 않게 한다. 되돌리려면 그 행을 지우고
    새로 만든 impact 허브를 삭제하면 된다.
    """
    from .models import UseCase, UseCaseFont, UseCasePhrase, Tag

    done = db.query(AppMeta).filter(AppMeta.key == IMPACT_HUB_MIGRATION_KEY).first()
    if done and done.value == "1":
        return

    tag = db.query(Tag).filter(Tag.name == "시선을 끄는 제목용").first()
    if tag is None:
        # 태그 이름이 바뀌었다면 함부로 만들지 않는다 — 같은 뜻의 태그가
        # 두 개 생기면 폰트가 양쪽으로 갈린다. 표시도 남기지 않고 다음 기동에 재시도.
        print("[migrate] 임팩트 허브 건너뜀 — '시선을 끄는 제목용' 태그를 찾지 못했습니다")
        return

    # ① 청첩장 허브 숨기기 (삭제하지 않는다 — 되돌릴 수 있어야 한다)
    wedding = db.query(UseCase).filter(UseCase.slug == "wedding").first()
    slot = wedding.sort_order if wedding else 0
    if wedding is not None and wedding.is_active:
        wedding.is_active = False
        print("[migrate] 청첩장 허브 비활성화 (데이터는 보존)")

    # ② 임팩트 허브 생성 — 청첩장이 있던 자리(sort_order)를 그대로 물려받아
    #    그리드 10칸이 유지된다.
    uc = db.query(UseCase).filter(UseCase.slug == "impact").first()
    if uc is None:
        uc = UseCase(slug="impact", sort_order=slot)
        db.add(uc)
    uc.title = "임팩트가 필요할 때!"
    uc.subtitle = "한 단어로 시선을 붙잡는 강한 제목용"
    uc.tag_id = tag.id
    uc.criteria = (
        "강조는 굵기만으로 만들어지지 않습니다. 획이 굵어도 글자통이 작으면 "
        "옆의 본문에 묻힙니다. 네모틀을 꽉 채우거나 형태에 개성이 있어 "
        "짧은 문구 하나로 화면을 잡아채는 서체만 골랐습니다."
    )
    uc.howto = (
        "본문의 2.5배 이상 크기로, 한 줄 8자 이내로 씁니다. "
        "한 화면에 강조는 하나만 두세요."
    )
    uc.tips = _IMPACT_TIPS
    uc.is_active = True
    db.flush()

    # ③ 상위픽 4종 — 폰트가 없으면 그 줄만 건너뛴다 (경고만 남긴다)
    db.query(UseCaseFont).filter(UseCaseFont.use_case_id == uc.id).delete()
    rank = 0
    missing = []
    for font_id, name, reason in _IMPACT_PICKS:
        f = db.query(Font).filter(Font.id == font_id).first()
        if f is None:
            missing.append(f"id={font_id}({name})")
            continue
        if f.name != name:
            print(f"[migrate] 임팩트 허브 폰트명 불일치 id={font_id}: DB='{f.name}' 기대='{name}'")
        rank += 1
        db.add(UseCaseFont(use_case_id=uc.id, font_id=font_id, rank=rank, reason=reason))
    if missing:
        print(f"[migrate] 임팩트 허브 폰트 미발견: {', '.join(missing)}")

    # ④ 문구 칩
    db.query(UseCasePhrase).filter(UseCasePhrase.use_case_id == uc.id).delete()
    for i, text_ in enumerate(_IMPACT_PHRASES):
        db.add(UseCasePhrase(use_case_id=uc.id, text=text_, sort_order=(i + 1) * 10))

    if done is None:
        db.add(AppMeta(key=IMPACT_HUB_MIGRATION_KEY, value="1"))
    else:
        done.value = "1"
    db.commit()
    print(f"[migrate] '임팩트가 필요할 때!' 허브 생성 완료 (상위픽 {rank}종, 태그 '{tag.name}')")


def _migrate_tag_axes(db: Session):
    """태그 3축 분리 마이그레이션 — DB당 딱 한 번만 실행된다.

    ① 태그 개명/병합(_TAG_RENAMES) ② axis 부여(_TAG_AXIS)
    ③ 모양 태그 고아 폰트 보완(_SHAPE_BACKFILL — 이미 모양 태그가 있으면 건너뜀)

    ⚠ 예전엔 부팅할 때마다 돌았다. 위 세 표가 전부 '태그 이름' 기준이라,
    어드민에서 카테고리 이름을 바꾸면 다음 배포에서 이 함수가 되돌려 놨다:
      · 바꾼 이름이 _TAG_RENAMES의 구 이름이면 ①이 그대로 개명해 버리고,
      · 모양 태그(손글씨·디스플레이 등)를 바꾸면 ③이 그 이름을 못 찾아
        같은 이름의 태그를 새로 만들어 붙였다 — 지운 이름이 매번 되살아났다.
    한 번 적용되면 끝인 일회성 정리 작업이므로 app_meta에 표시하고 다시는
    손대지 않는다. 운영 DB에서 강제로 다시 돌리려면 그 행을 지우면 된다.
    """
    from sqlalchemy import text as _sql_text
    from .models import Tag, Font

    done = db.query(AppMeta).filter(AppMeta.key == TAG_AXIS_MIGRATION_KEY).first()
    if done and done.value == "1":
        return

    # 이미 적용된 DB(= axis가 하나라도 채워져 있음)라면 표시만 남기고 건너뛴다.
    # 여기서 한 번 더 돌리면 지금 어드민에 걸려 있는 이름 변경을 마지막으로
    # 한 번 되돌리게 된다 — 그럴 이유가 없다.
    already = db.execute(
        _sql_text("SELECT COUNT(*) FROM tags WHERE axis IS NOT NULL")
    ).scalar() or 0
    if already:
        db.add(AppMeta(key=TAG_AXIS_MIGRATION_KEY, value="1"))
        db.commit()
        print("[migrate] 태그 3축 분리 — 이미 적용된 DB로 판단, 이후 실행하지 않음")
        return

    # ① 개명 또는 병합
    for old, new in _TAG_RENAMES.items():
        old_tag = db.query(Tag).filter(Tag.name == old).first()
        if not old_tag:
            continue
        new_tag = db.query(Tag).filter(Tag.name == new).first()
        if new_tag is None:
            old_tag.name = new
            print(f"[migrate] 태그 개명: {old} → {new}")
        else:
            for f in list(old_tag.fonts):
                if new_tag not in f.tags:
                    f.tags.append(new_tag)
                f.tags.remove(old_tag)
            db.delete(old_tag)
            print(f"[migrate] 태그 병합: {old} → {new}")
    db.flush()

    # ② axis 부여 — raw SQL 사용.
    # (모델에 axis 속성이 아직 배포되지 않은 중간 상태에서도 동작해야 하므로
    #  ORM 속성 접근 대신 UPDATE 문으로 처리. 단일 파일 순차 배포 안전성.)
    from sqlalchemy import text
    changed = 0
    for tag_name, axis in _TAG_AXIS.items():
        result = db.execute(
            text("UPDATE tags SET axis = :axis WHERE name = :name AND (axis IS NULL OR axis != :axis)"),
            {"axis": axis, "name": tag_name},
        )
        changed += result.rowcount or 0
    if changed:
        print(f"[migrate] tags.axis 부여: {changed}건")

    # ③ 모양 고아 보완 (ORM은 name/fonts 관계만 사용 — axis는 SQL로 후처리)
    shape_names = {n for n, a in _TAG_AXIS.items() if a == "shape"}
    tag_by_name = {t.name: t for t in db.query(Tag).all()}
    fixed = 0
    for font_name, shape_name in _SHAPE_BACKFILL.items():
        font = db.query(Font).filter(Font.name == font_name).first()
        if not font:
            continue
        if {t.name for t in font.tags} & shape_names:
            continue  # 이미 모양 태그 보유
        shape_tag = tag_by_name.get(shape_name)
        if shape_tag is None:
            shape_tag = Tag(name=shape_name)
            db.add(shape_tag)
            db.flush()
            db.execute(
                text("UPDATE tags SET axis = 'shape' WHERE name = :name"),
                {"name": shape_name},
            )
            tag_by_name[shape_name] = shape_tag
        font.tags.append(shape_tag)
        fixed += 1
    if fixed:
        print(f"[migrate] 모양 고아 보완: {fixed}건")

    db.add(AppMeta(key=TAG_AXIS_MIGRATION_KEY, value="1"))
    db.commit()


def _seed_admin(db: Session):
    if db.query(AdminUser).count() > 0:
        return
    admin = AdminUser(
        username=DEFAULT_ADMIN_USERNAME,
        password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
        must_change_password=True,
    )
    db.add(admin)
    db.commit()
    print(f"[seed] 기본 관리자 생성: {DEFAULT_ADMIN_USERNAME}")


def _seed_fonts_and_tags(db: Session):
    if db.query(Font).count() > 0:
        return
    if not SEED_PATH.exists():
        print(f"[seed] seed_data.json 없음: {SEED_PATH}")
        return
    with open(SEED_PATH, encoding="utf-8") as f:
        data = json.load(f)

    # 카테고리 먼저
    tag_map = {}
    for i, name in enumerate(data["tags"]):
        tag = Tag(name=name, sort_order=(i + 1) * 10)
        db.add(tag)
        tag_map[name] = tag
    db.flush()

    # 폰트 — has_file은 static/fonts/ 안에 파일이 있는지로 판단
    for i, fdata in enumerate(data["fonts"]):
        font_id = fdata["id"]
        has_file = (BUNDLED_FONTS_DIR / f"font-{font_id:03d}.woff2").exists()
        font = Font(
            id=font_id,
            name=fdata["name"],
            maker=fdata["maker"],
            weights=fdata.get("weights", "1종"),
            url=fdata.get("url", ""),
            stack=fdata.get("stack", "'Nanum Gothic',sans-serif"),
            is_english=fdata.get("is_english", False),
            has_file=has_file,
            sort_order=(i + 1) * 10,
            meta=fdata.get("meta", {}),
        )
        for tname in fdata.get("tags", []):
            if tname in tag_map:
                font.tags.append(tag_map[tname])
        db.add(font)
    db.commit()
    print(f"[seed] 폰트 {len(data['fonts'])}개, 카테고리 {len(data['tags'])}개 삽입")


from .pairing_data import PAIRING_SEED, PAIRING_SEED_VERSION


def _norm_name(s: str) -> str:
    """폰트 이름 정규화 — 공백 제거 + 소문자 (시드/업로드 표기 차이 흡수)"""
    return "".join((s or "").split()).lower()


def _seed_pairings(db: Session):
    """페어링 시드 삽입 (이름 매칭, 버전 관리).

    - 저장된 pairing_seed_version과 현재 버전이 다르면 지우고 재삽입
    - 이름을 DB 폰트 이름과 정규화 매칭, 실패한 조합은 스킵 (사이트엔 자동으로 안 보임)
    - 어드민 페어링 관리 도입 후에는 버전을 올리지 말 것 (수동 데이터 보호)
    """
    meta = db.query(AppMeta).filter(AppMeta.key == "pairing_seed_version").first()
    if meta and meta.value == PAIRING_SEED_VERSION:
        return  # 최신 버전 시드 이미 적용됨
    # 버전이 다르면 기존 시드를 지우고 재삽입 (어드민 관리 도입 후엔 버전 올리지 말 것)
    db.query(FontPairing).delete()
    if meta is None:
        meta = AppMeta(key="pairing_seed_version", value=PAIRING_SEED_VERSION)
        db.add(meta)
    else:
        meta.value = PAIRING_SEED_VERSION
    items = PAIRING_SEED

    fonts_by_norm = {}
    for font in db.query(Font).all():
        fonts_by_norm.setdefault(_norm_name(font.name), font)

    inserted, skipped = 0, []
    for i, it in enumerate(items):
        tf = fonts_by_norm.get(_norm_name(it.get("title_font_name", "")))
        bf = fonts_by_norm.get(_norm_name(it.get("body_font_name", "")))
        if not tf or not bf:
            skipped.append(f"#{it.get('id', i)} {it.get('title_font_name')}+{it.get('body_font_name')}")
            continue
        db.add(FontPairing(
            theme=it.get("theme", ""),
            title_font_id=tf.id,
            body_font_id=bf.id,
            sample_title=it.get("sample_title", ""),
            sample_body=it.get("sample_body", ""),
            description=it.get("description", ""),
            title_weight=int(it.get("title_weight", 700)),
            body_weight=int(it.get("body_weight", 400)),
            sort_order=(i + 1) * 10,
        ))
        inserted += 1
    db.commit()
    print(f"[seed] 페어링 {inserted}개 삽입 (v{PAIRING_SEED_VERSION})" + (f", 매칭실패 {len(skipped)}건: {', '.join(skipped)}" if skipped else ""))


from .use_case_data import USE_CASE_SEED, USE_CASE_SEED_VERSION


def _seed_use_cases(db: Session):
    """용도 허브 시드 삽입 (버전 관리).

    - 저장된 use_case_seed_version과 현재 버전이 다르면 지우고 재삽입
    - 폰트는 font_id로 연결하고, 시드에 적힌 이름과 실제 DB 폰트명을 대조해
      다르면 경고를 남긴다 (연결은 id 기준이라 끊어지지 않는다)
    - 존재하지 않는 font_id는 건너뛰되 반드시 로그를 남긴다 — 조용히 비는 허브가
      생기면 원인 추적에 시간이 든다
    - 어드민에서 편집한 이력이 있으면 시드는 아예 손대지 않는다 (아래 가드)
    """
    from .models import UseCase, UseCaseFont, UseCasePhrase

    # 어드민에서 한 번이라도 편집했다면 시드는 절대 덮어쓰지 않는다.
    # 버전만 올리면 지우고 다시 넣는 구조라, 이 방어가 없으면 운영자가
    # 다듬어 놓은 문구가 배포 한 번에 통째로 사라진다.
    edited = db.query(AppMeta).filter(AppMeta.key == "use_case_admin_edited").first()
    if edited and edited.value == "1":
        meta = db.query(AppMeta).filter(AppMeta.key == "use_case_seed_version").first()
        if not meta or meta.value != USE_CASE_SEED_VERSION:
            print(
                "[seed] 용도 허브 시드 건너뜀 — 어드민에서 편집된 이력이 있어 덮어쓰지 않습니다. "
                "시드로 되돌리려면 app_meta의 use_case_admin_edited 행을 지우세요."
            )
        return

    meta = db.query(AppMeta).filter(AppMeta.key == "use_case_seed_version").first()
    if meta and meta.value == USE_CASE_SEED_VERSION:
        return  # 최신 버전 시드 이미 적용됨

    db.query(UseCasePhrase).delete()
    db.query(UseCaseFont).delete()
    db.query(UseCase).delete()
    if meta is None:
        meta = AppMeta(key="use_case_seed_version", value=USE_CASE_SEED_VERSION)
        db.add(meta)
    else:
        meta.value = USE_CASE_SEED_VERSION

    tags_by_name = {t.name: t for t in db.query(Tag).all()}
    fonts_by_id = {f.id: f for f in db.query(Font).all()}

    inserted = 0
    missing_fonts = []
    renamed_fonts = []
    missing_tags = []

    for i, uc in enumerate(USE_CASE_SEED):
        tag_id = None
        if uc["tag_name"]:
            tag = tags_by_name.get(uc["tag_name"])
            if tag is None:
                missing_tags.append(f"{uc['slug']}←{uc['tag_name']}")
            else:
                tag_id = tag.id

        row = UseCase(
            slug=uc["slug"],
            title=uc["title"],
            subtitle=uc.get("subtitle", ""),
            tag_id=tag_id,
            criteria=uc.get("criteria", ""),
            howto=uc.get("howto", ""),
            tips=uc.get("tips", []),
            is_active=True,
            sort_order=(i + 1) * 10,
        )
        db.add(row)
        db.flush()

        for rank, (font_id, expected_name, reason) in enumerate(uc.get("fonts", []), start=1):
            font = fonts_by_id.get(font_id)
            if font is None:
                missing_fonts.append(f"{uc['slug']}#{rank} id={font_id}({expected_name})")
                continue
            if font.name != expected_name:
                renamed_fonts.append(f"id={font_id} 시드'{expected_name}' vs DB'{font.name}'")
            db.add(UseCaseFont(
                use_case_id=row.id,
                font_id=font_id,
                rank=rank,
                reason=reason,
            ))

        for j, text_ in enumerate(uc.get("phrases", [])):
            db.add(UseCasePhrase(
                use_case_id=row.id,
                text=text_,
                sort_order=(j + 1) * 10,
            ))
        inserted += 1

    db.commit()

    print(f"[seed] 용도 허브 {inserted}개 삽입 (v{USE_CASE_SEED_VERSION})")
    if missing_tags:
        print(f"[seed] ⚠ 용도 허브 태그 미발견 {len(missing_tags)}건: {', '.join(missing_tags)}")
    if missing_fonts:
        print(f"[seed] ⚠ 용도 허브 폰트 미발견 {len(missing_fonts)}건: {', '.join(missing_fonts)}")
    if renamed_fonts:
        print(f"[seed] ℹ 폰트명 변경 감지 {len(renamed_fonts)}건 (id 연결이라 정상 동작): {', '.join(renamed_fonts)}")


def _seed_gif_use_cases(db: Session):
    """GIF 생성기 용도 5종 + 용도별 폰트.

    어드민이 폰트를 하나라도 넣거나 뺐으면 그 뒤로는 손대지 않는다.
    이 용도 목록은 '운영자가 계속 다듬는 것'이 전제라 시드가 덮어쓰면
    작업이 통째로 사라진다 — 템플릿 시드와 같은 방어다.
    """
    from .models import GifUseCase, GifUseCaseFont
    from .gif_use_case_data import GIF_USE_CASES, GIF_USE_CASE_SEED_VERSION

    edited = db.query(AppMeta).filter(AppMeta.key == "gif_use_case_admin_edited").first()
    if edited and edited.value == "1":
        return

    meta = db.query(AppMeta).filter(AppMeta.key == "gif_use_case_seed_version").first()
    if meta and meta.value == GIF_USE_CASE_SEED_VERSION:
        return

    db.query(GifUseCaseFont).delete()
    db.query(GifUseCase).delete()
    if meta is None:
        db.add(AppMeta(key="gif_use_case_seed_version", value=GIF_USE_CASE_SEED_VERSION))
    else:
        meta.value = GIF_USE_CASE_SEED_VERSION

    font_ids = {f.id for f in db.query(Font.id).all()}
    missing = []
    for i, uc in enumerate(GIF_USE_CASES):
        row = GifUseCase(
            slug=uc["slug"], title=uc["title"], subtitle=uc.get("subtitle", ""),
            is_active=True, sort_order=i * 10,
        )
        db.add(row)
        db.flush()          # id가 있어야 폰트 줄을 붙인다
        rank = 0
        for fid in uc["fonts"]:
            if fid not in font_ids:
                missing.append(f"{uc['slug']}←폰트{fid}")
                continue
            db.add(GifUseCaseFont(gif_use_case_id=row.id, font_id=fid, rank=rank))
            rank += 1
    db.commit()
    print(f"[seed] GIF 용도 {len(GIF_USE_CASES)}종 삽입 (v{GIF_USE_CASE_SEED_VERSION})")
    if missing:
        print(f"[seed] ⚠ GIF 용도 폰트 미발견 {len(missing)}건: {', '.join(missing)}")


def _seed_gif_templates(db: Session):
    """GIF 생성기 템플릿 시드 48종.

    운영자가 어드민(/admin/gif)에서 하나라도 저장·삭제하면 그 뒤로는
    시드가 절대 손대지 않는다. 이 방어가 없으면 다듬어 놓은 템플릿이
    배포 한 번에 통째로 되돌아간다 — 용도 허브 시드와 같은 이유다.

    없는 폰트 id는 건너뛰지 않고 font_id=None으로 넣는다. 건너뛰면
    번호가 비어 조용히 47종이 되고, 왜 하나가 없는지 나중에 못 찾는다.
    어드민 목록에서 폰트 없는 템플릿으로 보이는 편이 낫다.
    """
    from .models import GifTemplate
    from .gif_template_data import GIF_TEMPLATES, GIF_TEMPLATE_SEED_VERSION

    edited = db.query(AppMeta).filter(AppMeta.key == "gif_template_admin_edited").first()
    if edited and edited.value == "1":
        return

    meta = db.query(AppMeta).filter(AppMeta.key == "gif_template_seed_version").first()
    if meta and meta.value == GIF_TEMPLATE_SEED_VERSION:
        return  # 최신 버전 시드 이미 적용됨

    db.query(GifTemplate).delete()
    if meta is None:
        db.add(AppMeta(key="gif_template_seed_version", value=GIF_TEMPLATE_SEED_VERSION))
    else:
        meta.value = GIF_TEMPLATE_SEED_VERSION

    font_ids = {f.id for f in db.query(Font.id).all()}
    missing = []
    for t in GIF_TEMPLATES:
        fid = t["font_id"]
        if fid not in font_ids:
            missing.append(f"{t['number']}←폰트{fid}")
            fid = None
        db.add(GifTemplate(
            number=t["number"], title=t["title"], hub_slug=t["hub_slug"],
            anim=t["anim"], anim_category=t["anim_category"], effect=t["effect"],
            ratio=t["ratio"], gif_rating=t["gif_rating"],
            font_id=fid, font_weight=t["font_weight"],
            sample_text=t["sample_text"], config=t["config"],
            is_active=t["is_active"], sort_order=t["sort_order"],
        ))
    db.commit()
    print(f"[seed] GIF 템플릿 {len(GIF_TEMPLATES)}종 삽입 (v{GIF_TEMPLATE_SEED_VERSION})")
    if missing:
        print(f"[seed] ⚠ GIF 템플릿 폰트 미발견 {len(missing)}건: {', '.join(missing)}")
