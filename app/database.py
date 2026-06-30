"""MySQL 데이터베이스 연결 및 세션 관리

카페24 AI Space는 다음 환경변수를 자동 주입합니다:
- DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

MySQL 환경변수가 없으면 영구 저장 가능한 경로의 SQLite로 fallback.
카페24는 /app/user_data/만 컨테이너 재배포 시 보존되므로 거기 저장.
"""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


def get_database_url() -> str:
    """환경변수에서 DB URL을 만들어 반환.

    카페24가 주입하는 env가 없으면 영구 보존되는 SQLite로 fallback.
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

    # SQLite fallback — /app/user_data/는 카페24가 영구 보존하는 유일한 경로
    # 로컬 개발 시에는 LOCAL_DB_PATH 환경변수로 다른 경로 지정 가능
    default_path = "/app/user_data/freefontpick.db"
    db_path = os.getenv("LOCAL_DB_PATH", default_path)
    # 디렉토리 자동 생성
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        # 권한 문제 등이 있으면 /tmp로 마지막 fallback
        db_path = "/tmp/freefontpick_local.db"
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
