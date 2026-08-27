"""FreeFontPick 백엔드 — FastAPI 앱 진입점

- API: /api/* 에 등록
- 정적 파일: /static/ 아래 + 루트(/) 도 정적 서빙
- 세션 미들웨어: itsdangerous SessionMiddleware
"""
import hashlib
import os
import re
import secrets
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from .seed import init_db
from .routers import auth, fonts, tags, notices, files as files_router, likes, seo, submissions, design, pairings, og_image, piece_image, preview_phrases, wisefont, use_cases, use_cases_admin, use_case_route, sample_image, db_migrate, gif_templates, gif, font_pair

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

    # 갤러리 서브셋을 걷어냈다(2026-08). 예전 배포가 user_data에 만들어 둔
    # 파일이 남아 있으므로 한 번 치운다. 다음 배포 때 이 블록은 지운다.
    try:
        import shutil
        from pathlib import Path
        old = Path(os.getenv("SUBSETS_DIR", "/app/user_data/subsets"))
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
            print("[startup] 남아 있던 서브셋 파일을 치웠습니다", flush=True)
    except Exception:
        pass

    # 조회수 집계의 오래된 칸을 지운다.
    try:
        from .database import SessionLocal
        from .font_views import prune
        db = SessionLocal()
        try:
            n = prune(db)
        finally:
            db.close()
        if n:
            print(f"[startup] 오래된 조회 기록 {n}행 정리", flush=True)
    except Exception:
        pass

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

# ─── API 응답 캐시 방지 ─────────────────────────────────────
# 커스텀 도메인(freefontpick.co.kr) 앞단에서 /api/* GET 응답이 캐시되어,
# 어드민에서 데이터를 고쳐도 사용자에게 옛 데이터가 나가는 문제가 있었다.
# (2026-08 태그 axis 마이그레이션 때 원본 서버와 도메인 응답이 달랐던 건이 발단)
#
# 단, /api 아래에는 캐시가 이득인 바이너리 응답이 섞여 있으므로 제외한다:
#   - /api/fonts/{id}/og-image.png : OG 이미지 (디스크 캐시 파일)
#   - /api/fonts/{id}/file         : woff2 폰트 파일 (매 페이지뷰마다 재다운로드되면 치명적)
#   - /api/fonts/{id}/sample-image : 상세페이지 샘플 이미지
#   - /api/fonts/{id}/webfont.css  : 외부용 웹폰트 CSS. 홍보물·프레스킷이 매번
#     새로 받을 이유가 없고, 라우터가 직접 max-age=300을 지정한다.
_CACHE_EXEMPT_SUFFIXES = ("/og-image.png", "/file", "/sample-image", "/webfont.css")


# ══════════════════════════════════════════════════════════════
# 정적 JS/CSS 캐시 무효화
#
# 카페24 앞단이 /static/* 에 Cache-Control: max-age=315360000(10년)을
# 붙인다. 앱이 설정하는 값이 아니라 우리가 끌 수 없다. 그래서 배포로
# api-client.js를 고쳐도 방문자 브라우저는 10년 전 파일을 계속 쓴다.
# 실제로 어드민의 '용도 · 폰트 관리'가 이것 때문에 빈 화면이었다 —
# HTML은 새 파일인데 거기서 부르는 GifUseCaseStore가 옛 JS에는 없었다.
#
# 프록시 설정을 못 바꾸니 URL을 바꾼다. HTML을 내보낼 때
# /static/api-client.js → /static/api-client.js?v=1a2b3c4d 로 고쳐 쓰면
# 파일이 바뀔 때마다 주소가 달라져 캐시가 비켜간다. 주소가 그대로인
# 동안에는 10년 캐시가 그대로 살아 있어 속도 손해도 없다.
# ══════════════════════════════════════════════════════════════
# /static/x.js 와 /header.css(루트로도 서빙된다) 둘 다 잡는다.
# 홈·소개·FAQ·폰트 상세는 header.css를 루트 경로로 부르고 있어서
# /static/ 만 보면 정작 손봐야 할 페이지들이 통째로 빠진다.
_ASSET_REF = re.compile(r'(src|href)="(/(?:static/)?[\w./-]+\.(?:js|css))"')
_asset_versions: dict = {}


def _asset_version(url_path: str) -> str:
    """파일 '내용'이 바뀔 때만 바뀌는 짧은 문자열.

    수정시각이 아니라 내용으로 해시하는 이유: git으로 배포하면 파일을 새로
    받으면서 수정시각이 전부 바뀐다. 시각으로 잡으면 고치지도 않은 파일까지
    배포할 때마다 다시 내려받게 된다.

    한 번 계산하면 프로세스가 살아있는 동안 재사용한다 —
    정적 파일은 재배포(=새 컨테이너)로만 바뀐다. 실제로 참조된 파일만
    읽으므로 시작이 느려지지도 않는다.
    """
    if url_path in _asset_versions:
        return _asset_versions[url_path]
    rel = url_path[len("/static/"):] if url_path.startswith("/static/") else url_path[1:]
    try:
        v = hashlib.md5((STATIC_DIR / rel).read_bytes()).hexdigest()[:8]
    except OSError:
        v = ""           # 실제 파일이 아니면 주소를 건드리지 않는다 (라우트일 수 있다)
    _asset_versions[url_path] = v
    return v


def _stamp_assets(html: str) -> str:
    def rep(m):
        v = _asset_version(m.group(2))
        return f'{m.group(1)}="{m.group(2)}?v={v}"' if v else m.group(0)
    return _ASSET_REF.sub(rep, html)


@app.middleware("http")
async def stamp_static_assets(request: Request, call_next):
    response = await call_next(request)
    if not response.headers.get("content-type", "").startswith("text/html"):
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    try:
        body = _stamp_assets(body.decode("utf-8")).encode("utf-8")
    except UnicodeDecodeError:
        pass                                  # HTML이 아니면 손대지 않고 그대로 돌려준다

    out = Response(status_code=response.status_code)
    out.body = body
    # dict(response.headers)로 옮기면 같은 이름의 헤더가 하나로 뭉개진다.
    # Set-Cookie가 둘 이상일 때 로그인 세션이 조용히 사라지므로 raw로 옮긴다.
    out.raw_headers = [
        (k, v) for (k, v) in response.raw_headers if k.lower() != b"content-length"
    ] + [(b"content-length", str(len(body)).encode())]
    return out


@app.middleware("http")
async def no_store_for_api(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/") and not path.endswith(_CACHE_EXEMPT_SUFFIXES):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# API 라우터 등록
app.include_router(auth.router)
app.include_router(fonts.router)
app.include_router(tags.router)
app.include_router(notices.router)
app.include_router(files_router.router)
app.include_router(likes.router)
app.include_router(seo.router)
app.include_router(submissions.router)
app.include_router(pairings.router)
app.include_router(font_pair.router)
app.include_router(preview_phrases.router)
app.include_router(use_cases.router)
app.include_router(use_cases_admin.router)
app.include_router(sample_image.router)
app.include_router(og_image.router)
app.include_router(og_image.hub_router)
# 홍보물용 글자 조각 PNG. og_image 와 같은 /api/fonts prefix 라 함께 둔다.
app.include_router(piece_image.router)
app.include_router(gif_templates.router)
# SQLite → MySQL 일회용 이관 도구 (관리자 전용). 이관이 끝나면 지워도 된다.
app.include_router(db_migrate.router)
# wisefont / design / use 라우터는 catch-all(/{full_path:path})보다 반드시 먼저 등록해야
# /wisefont/{slug}, /design/{id}, /use/{slug}, /find-font 요청이 catch-all에 가로채이지 않는다.
app.include_router(wisefont.router)
app.include_router(use_case_route.router)
app.include_router(gif.router)
app.include_router(design.router)


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
