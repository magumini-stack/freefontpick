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
from .models import Font, Tag, AdminUser
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
    db = SessionLocal()
    try:
        _seed_admin(db)
        _seed_fonts_and_tags(db)
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
