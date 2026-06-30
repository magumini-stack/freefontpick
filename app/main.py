"""FreeFontPick 백엔드 — FastAPI 앱 진입점

- API: /api/* 에 등록
- 정적 파일: /static/ 아래 + 루트(/) 도 정적 서빙
- 세션 미들웨어: itsdangerous SessionMiddleware
"""
import os
import secrets
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from .seed import init_db
from .routers import auth, fonts, tags, notices, files as files_router, likes, seo

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 DB 초기화 + 시드 데이터 로드.

    실패해도 앱은 계속 살아있도록 try/except로 감싼다.
    그래야 헬스체크가 통과되고 로그로 원인을 확인할 수 있다.
    """
    try:
        init_db()
        print("[startup] init_db OK")
    except Exception as e:
        import traceback
        print(f"[startup] init_db 실패 (앱은 계속 실행됨): {e}")
        traceback.print_exc()
    yield


app = FastAPI(
    title="FreeFontPick API",
    version="1.0.0",
    lifespan=lifespan,
)

# 세션 비밀키 — 운영 환경에선 SESSION_SECRET 환경변수로 주입 권장
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_urlsafe(32)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="ffp_session",
    https_only=False,   # 카페24가 SSL 종료 후 HTTP로 전달 가능
    same_site="lax",
    max_age=60 * 60 * 24 * 7,  # 7일
)

# CORS — 같은 도메인에서 서빙되므로 보수적으로 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 도메인 확정되면 좁히기
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(auth.router)
app.include_router(fonts.router)
app.include_router(tags.router)
app.include_router(notices.router)
app.include_router(files_router.router)
app.include_router(likes.router)
app.include_router(seo.router)


# 헬스체크 — DB 종류와 경로/호스트도 함께 노출 (운영 데이터 보존 진단용)
@app.get("/api/health")
def health():
    """기본 헬스 + DB 연결 상태 + 폰트/태그 카운트 + DB 종류"""
    info = {"status": "ok", "service": "freefontpick-api", "version": "1.0.0"}
    try:
        from .database import SessionLocal, DATABASE_URL
        from .models import Font, Tag, AdminUser

        # DB 종류 식별 (비밀번호는 가림)
        if DATABASE_URL.startswith("mysql"):
            info["db_type"] = "mysql"
            # mysql+pymysql://user:pass@host:port/db?...
            try:
                # 비밀번호 부분만 마스킹
                masked = DATABASE_URL
                if "://" in masked and "@" in masked:
                    prefix, rest = masked.split("://", 1)
                    if "@" in rest:
                        creds, host = rest.split("@", 1)
                        if ":" in creds:
                            user, _ = creds.split(":", 1)
                            masked = f"{prefix}://{user}:***@{host}"
                info["db_url"] = masked
            except Exception:
                info["db_url"] = "mysql (parse error)"
        elif DATABASE_URL.startswith("sqlite"):
            info["db_type"] = "sqlite"
            info["db_url"] = DATABASE_URL
        else:
            info["db_type"] = "other"

        db = SessionLocal()
        try:
            info["fonts"] = db.query(Font).count()
            info["tags"] = db.query(Tag).count()
            info["admins"] = db.query(AdminUser).count()
            info["db"] = "connected"
        finally:
            db.close()
    except Exception as e:
        info["db"] = "error"
        info["db_error"] = str(e)[:200]
    return info


# ─── 정적 파일 서빙 ─────────────────────────────────────
# 우선순위: API 경로(/api/*)가 먼저 매칭되고, 나머지는 정적 파일

# /static/* 명시적 경로 (이미지, JS, CSS 등 직접 참조)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/{full_path:path}")
async def serve_static(full_path: str):
    """루트의 모든 경로 → static/ 폴더의 파일로 서빙

    - / → static/index.html
    - /admin.html → static/admin.html
    - /logo.png → static/logo.png
    """
    # 빈 경로는 index
    if not full_path or full_path == "/":
        target = STATIC_DIR / "index.html"
    else:
        target = STATIC_DIR / full_path

    # 디렉토리 traversal 방지
    try:
        target = target.resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
    except Exception:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    if not target.exists() or not target.is_file():
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return FileResponse(target)
