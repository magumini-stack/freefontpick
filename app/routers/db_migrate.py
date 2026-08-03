"""SQLite → MySQL 일회용 이관 도구 (관리자 전용).

배경
----
2026-08, 카페24가 이 프로젝트에 MySQL을 자동 주입하기 시작하면서 앱이 빈 MySQL로
갈아탔다. 그때까지 SQLite(/app/user_data/freefontpick.db)에 쌓아온 폰트 193종·
페어링 273개·문구 30개·공지 2개가 통째로 안 보이게 됐다. 급한 불은
database.py의 FORCE_SQLITE 스위치로 껐고, 이 모듈은 그 데이터를 MySQL로 옮긴다.

설계 원칙
---------
1. **원본을 절대 건드리지 않는다.** SQLite는 읽기 전용으로만 연다.
   실패해도 FORCE_SQLITE=1로 두면 사고 이전 상태 그대로다.
2. **같은 Table 객체로 읽고 쓴다.** 모델에 선언된 타입을 양쪽에 적용해야
   JSON·Boolean·DateTime이 SQLite의 TEXT/INTEGER 표현과 MySQL 사이에서
   올바르게 변환된다. 원시 SQL로 옮기면 JSON 컬럼이 문자열로 박힌다.
3. **id를 그대로 옮긴다.** 폰트 id는 use_case_fonts·font_pairings·gif_templates가
   참조하고 시드 데이터(use_case_data.py)도 id로 폰트를 지목한다. 새로 매기면
   전부 끊어진다.
4. **미리보기(dry-run)가 기본.** 실제로 쓰려면 confirm=대상DB이름 을 넘겨야 한다.
"""
import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import create_engine, select, text

from ..auth import require_password_changed
from ..database import Base, engine as dst_engine, DATABASE_URL

router = APIRouter(prefix="/api/admin", tags=["db-migrate"])

SQLITE_PATH = os.getenv("MIGRATE_SQLITE_PATH", "/app/user_data/freefontpick.db")

# 외래키 안전 순서 — 부모부터. 지울 때는 이 순서의 역순.
TABLE_ORDER: List[str] = [
    "tags",
    "fonts",
    "notices",
    "admin_users",
    "font_submissions",
    "preview_phrases",
    "app_meta",
    "font_tags",
    "font_weights",
    "font_pairings",
    "submission_answers",
    "use_cases",
    "use_case_fonts",
    "use_case_phrases",
    "gif_templates",
]


def _src_engine():
    p = Path(SQLITE_PATH)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"SQLite 파일이 없습니다: {SQLITE_PATH}")
    # 읽기 전용으로 연다 — 원본을 실수로도 바꾸지 않기 위해
    return create_engine(f"sqlite:///file:{p}?mode=ro&uri=true",
                         connect_args={"check_same_thread": False})


def _ordered_tables():
    """모델에 선언된 Table 객체를 FK 안전 순서로."""
    known = Base.metadata.tables
    out = []
    for name in TABLE_ORDER:
        if name in known:
            out.append(known[name])
    # TABLE_ORDER에 빠진 테이블이 생기면 뒤에 붙여 조용히 누락되지 않게 한다
    for name, t in known.items():
        if name not in TABLE_ORDER:
            out.append(t)
    return out


@router.get("/db-compare")
def db_compare(_admin=Depends(require_password_changed)) -> dict:
    """SQLite와 현재 DB의 테이블별 행 수를 나란히 보여준다. 아무것도 바꾸지 않는다."""
    src = _src_engine()
    rows = {}
    with src.connect() as s, dst_engine.connect() as d:
        for t in _ordered_tables():
            def count(conn):
                try:
                    return conn.execute(select(text("COUNT(*)")).select_from(t)).scalar()
                except Exception as e:
                    return f"오류({e.__class__.__name__})"
            rows[t.name] = {"sqlite": count(s), "current": count(d)}
    return {
        "sqlite_path": SQLITE_PATH,
        "current_db": DATABASE_URL.split("://")[0],
        "tables": rows,
    }


@router.post("/db-migrate")
def db_migrate(
    confirm: str = Query("", description="실행하려면 'mysql'을 넘긴다. 비우면 미리보기."),
    _admin=Depends(require_password_changed),
) -> dict:
    """SQLite의 모든 테이블을 현재 DB(MySQL)로 복사한다.

    대상 테이블을 먼저 비우고 넣는다(덮어쓰기). SQLite는 읽기만 한다.
    confirm=mysql 이 없으면 옮길 행 수만 세어 돌려준다.
    """
    if DATABASE_URL.startswith("sqlite"):
        raise HTTPException(
            status_code=400,
            detail="현재 앱이 SQLite를 쓰고 있어 이관할 대상이 없습니다. "
                   "FORCE_SQLITE를 끄고 MySQL로 붙은 상태에서 실행하세요.",
        )

    src = _src_engine()
    tables = _ordered_tables()
    plan, moved = {}, {}

    # 1) 읽기 — 원본에서 전부 메모리로. 폰트 193행 수준이라 부담 없다.
    data = {}
    with src.connect() as s:
        for t in tables:
            try:
                data[t.name] = [dict(r._mapping) for r in s.execute(select(t))]
            except Exception:
                data[t.name] = []   # SQLite에 없는 신규 테이블(gif_templates 등)
            plan[t.name] = len(data[t.name])

    if confirm != "mysql":
        return {"dry_run": True, "would_copy": plan,
                "hint": "실제로 옮기려면 ?confirm=mysql 을 붙이세요"}

    # 2) 쓰기 — 자식부터 지우고, 부모부터 넣는다.
    with dst_engine.begin() as d:
        is_mysql = DATABASE_URL.startswith("mysql")
        if is_mysql:
            d.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        try:
            for t in reversed(tables):
                d.execute(t.delete())
            for t in tables:
                rows = data.get(t.name) or []
                if rows:
                    d.execute(t.insert(), rows)
                moved[t.name] = len(rows)
        finally:
            if is_mysql:
                d.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    # 3) 검증 — 옮긴 뒤 실제 행 수를 다시 센다
    verify = {}
    with dst_engine.connect() as d:
        for t in tables:
            try:
                verify[t.name] = d.execute(select(text("COUNT(*)")).select_from(t)).scalar()
            except Exception as e:
                verify[t.name] = f"오류({e.__class__.__name__})"

    mismatch = {k: {"copied": moved.get(k), "in_db": verify.get(k)}
                for k in moved if moved.get(k) != verify.get(k)}
    return {
        "dry_run": False,
        "copied": moved,
        "verified": verify,
        "mismatch": mismatch or None,
        "ok": not mismatch,
        "next": "이관이 맞으면 FORCE_SQLITE 환경변수를 삭제해 MySQL로 전환하세요",
    }
