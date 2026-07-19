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
    db = SessionLocal()
    try:
        _seed_admin(db)
        _seed_fonts_and_tags(db)
        _seed_pairings(db)
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
