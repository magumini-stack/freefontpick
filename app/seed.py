"""DB 초기화 + 142개 폰트 시드 데이터 삽입

앱 시작 시 한 번 실행됨:
1. DB 테이블 생성 (없으면)
2. admin 계정이 없으면 기본 계정 생성 (admin / 임시비번 / must_change_password=True)
3. 카테고리/폰트가 비어있으면 seed_data.json에서 142개 일괄 삽입
4. /fonts/ 에 묶여있는 woff2 파일들을 /app/user_data/fonts/ 로 복사 (영구 보존)
"""
import json
import os
import shutil
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func

from .database import engine, SessionLocal, Base
from .models import Font, Tag, AdminUser
from .auth import hash_password


SEED_PATH = Path(__file__).resolve().parent.parent / "seed_data.json"
# 정적 배포에 묶인 초기 폰트 파일들
BUNDLED_FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
# 영구 저장 경로
PERSISTENT_FONTS_DIR = Path(os.getenv("FONTS_DIR", "/app/user_data/fonts"))

DEFAULT_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
# 첫 로그인용 임시 비밀번호 — must_change_password=True로 시작
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_INITIAL_PASSWORD", "freefontpick2026!")


def init_db():
    """테이블 생성 + 시드 데이터 + 폰트 파일 복사"""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _seed_admin(db)
        _seed_fonts_and_tags(db)
    finally:
        db.close()

    _copy_bundled_fonts()


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
    print(f"[seed] 기본 관리자 생성: {DEFAULT_ADMIN_USERNAME} (첫 로그인 시 비밀번호 변경 필요)")


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

    # 폰트
    for i, fdata in enumerate(data["fonts"]):
        font = Font(
            id=fdata["id"],
            name=fdata["name"],
            maker=fdata["maker"],
            weights=fdata.get("weights", "1종"),
            url=fdata.get("url", ""),
            stack=fdata.get("stack", "'Nanum Gothic',sans-serif"),
            is_english=fdata.get("is_english", False),
            has_file=False,  # 아래에서 파일 복사 후 갱신
            sort_order=(i + 1) * 10,
            meta=fdata.get("meta", {}),
        )
        for tname in fdata.get("tags", []):
            if tname in tag_map:
                font.tags.append(tag_map[tname])
        db.add(font)
    db.commit()
    print(f"[seed] 폰트 {len(data['fonts'])}개, 카테고리 {len(data['tags'])}개 삽입 완료")


def _copy_bundled_fonts():
    """배포에 묶인 폰트 파일을 영구 저장 경로로 복사

    /app/user_data/fonts/font-XXX.woff2 가 없으면 /app/fonts/ 에서 가져옴.
    이미 있으면 건드리지 않음 (운영자가 새로 올린 파일 보존).
    """
    if not BUNDLED_FONTS_DIR.exists():
        print(f"[seed] 번들 폰트 폴더 없음: {BUNDLED_FONTS_DIR}")
        return
    PERSISTENT_FONTS_DIR.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src in BUNDLED_FONTS_DIR.glob("*.woff2"):
        dst = PERSISTENT_FONTS_DIR / src.name
        if dst.exists():
            continue
        shutil.copy2(src, dst)
        copied += 1
    print(f"[seed] 번들 폰트 {copied}개를 {PERSISTENT_FONTS_DIR}로 복사")

    # has_file 플래그 갱신
    db = SessionLocal()
    try:
        for src in PERSISTENT_FONTS_DIR.glob("font-*.woff2"):
            stem = src.stem  # font-001
            try:
                font_id = int(stem.split("-")[1])
            except (IndexError, ValueError):
                continue
            font = db.query(Font).filter(Font.id == font_id).first()
            if font and not font.has_file:
                font.has_file = True
        db.commit()
    finally:
        db.close()
