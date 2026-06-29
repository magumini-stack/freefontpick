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
from .routers import auth, fonts, tags, notices, files as files_router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 DB 초기화 + 시드 데이터 로드"""
    init_db()
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


# 헬스체크
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "freefontpick-api", "version": "1.0.0"}


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
    - /fonts/font-001.woff2 → /api/fonts/X/file 로 안내해야 하므로 여기서 처리하지 않음
       (메인 페이지의 폰트 로딩이 API 경로를 사용하도록 수정 필요)
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
        # SPA-스타일 fallback이 필요하다면 index.html 반환
        # 우리 사이트는 멀티페이지라 404가 맞음
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return FileResponse(target)
