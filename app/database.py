"""MySQL 데이터베이스 연결 및 세션 관리

카페24 AI Space는 다음 환경변수를 자동 주입합니다:
- DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

로컬 개발 시에는 환경변수를 직접 설정하거나 SQLite로 대체합니다.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


def get_database_url() -> str:
    """환경변수에서 DB URL을 만들어 반환.

    카페24가 주입하는 env가 없으면 로컬 SQLite로 fallback.
    """
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")
    db_port = os.getenv("DB_PORT", "3306")

    if all([db_host, db_user, db_password, db_name]):
        return (
            f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            f"?charset=utf8mb4"
        )

    # 로컬 fallback (개발용)
    db_path = os.getenv("LOCAL_DB_PATH", "/tmp/freefontpick_local.db")
    return f"sqlite:///{db_path}"


DATABASE_URL = get_database_url()

# MySQL은 pool_pre_ping으로 죽은 커넥션 자동 감지
engine_kwargs = {"pool_pre_ping": True, "pool_recycle": 3600}
if DATABASE_URL.startswith("sqlite"):
    # SQLite는 멀티스레드용 옵션
    engine_kwargs = {"connect_args": {"check_same_thread": False}}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: 요청마다 세션 1개를 만들고 끝나면 닫음"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
