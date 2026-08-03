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


def _force_sqlite() -> bool:
    """MySQL 환경변수가 있어도 SQLite를 계속 쓰게 하는 스위치.

    2026-08, 카페24가 이 프로젝트에 MySQL을 자동 주입하기 시작하면서 앱이
    빈 MySQL로 갈아탔다. 그때까지 SQLite(/app/user_data/freefontpick.db)에
    쌓아온 폰트 191종·페어링 268개·공지·미리보기 문구가 통째로 안 보이게 됐다.
    DB 자격증명은 플랫폼이 주입하는 값이라 프로젝트 환경변수에서 지울 수 없어,
    앱 쪽에서 무시할 수단이 필요했다.

    데이터를 MySQL로 이관하기 전까지 FORCE_SQLITE=1로 둔다.
    이관이 끝나면 이 환경변수만 지우면 자동으로 MySQL을 쓴다.
    """
    return os.getenv("FORCE_SQLITE", "").strip().lower() in ("1", "true", "yes", "on")


def get_database_url() -> str:
    """환경변수에서 DB URL을 만들어 반환.

    카페24가 주입하는 env가 없거나 FORCE_SQLITE가 켜져 있으면
    영구 보존되는 SQLite를 쓴다.
    """
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")
    db_port = os.getenv("DB_PORT", "3306")

    if all([db_host, db_user, db_password, db_name]) and not _force_sqlite():
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

# 어느 DB를 잡았는지 배포 로그에 남긴다. 비밀번호는 찍지 않는다.
# (MySQL/SQLite가 조용히 바뀌면 데이터가 통째로 안 보이는 사고로 이어진다)
if DATABASE_URL.startswith("sqlite"):
    print(f"[db] SQLite 사용: {DATABASE_URL}"
          f"{' (FORCE_SQLITE=on — MySQL 무시)' if _force_sqlite() else ''}")
else:
    print(f"[db] MySQL 사용: {os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}")

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
