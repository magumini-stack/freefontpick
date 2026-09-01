"""FreeFontPick 백엔드 — FastAPI 앱 진입점

- API: /api/* 에 등록
- 정적 파일: /static/ 아래 + 루트(/) 도 정적 서빙
- 세션 미들웨어: itsdangerous SessionMiddleware
"""
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response)
from starlette.middleware.sessions import SessionMiddleware

from .header import inject_header, not_found_page
from .seed import init_db
from .site import SITE_URL
from .routers import auth, fonts, tags, notices, files as files_router, likes, seo, submissions, design, pairings, og_image, piece_image, preview_phrases, wisefont, use_cases, use_cases_admin, use_case_route, magazine, sample_image, db_migrate, gif_templates, gif, font_pair, stats

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


# ── 정규 주소로 모으기 (http→https, www 제거) ────────────────────
# 같은 사이트가 http/https × www 유무로 네 주소에서 열리면 검색엔진이
# 중복으로 본다. canonical 태그로 한 번 정리해 두었지만, 리다이렉트로
# 실제 응답을 하나로 모으는 편이 낫다.
#
# 주의: TLS 는 앞단에서 끊기므로 앱이 보는 request.url.scheme 은 늘 http 다.
# 그걸로 판단하면 https 로 들어온 요청까지 https 로 다시 보내 무한 루프가
# 된다. 방문자가 무슨 프로토콜을 썼는지는 _visitor_scheme 으로만 판단한다.
CANONICAL_HOST = urlsplit(SITE_URL).hostname or "freefontpick.co.kr"

# 옛 도메인 → 새 도메인 301. 쉼표로 여러 개 적는다.
#
#     LEGACY_HOSTS=freefontpick.co.kr,www.freefontpick.co.kr
#
# 도메인을 옮길 때 **경로를 그대로 물고 가는 것**이 핵심이다. 등록기관의
# 도메인 포워딩 기능은 대개 모든 요청을 루트로 보내 버려서, 색인된
# /font/{id} 239개가 전부 첫 화면으로 뭉개진다. 그래서 포워딩에 맡기지
# 않고 앱이 직접 301 한다. 옛 스페이스를 최소 6개월 살려 두어야 한다.
#
# 기본값은 비어 있다 — 이사 전에는 켜지 않는다. 그리고 지금 쓰는 도메인이
# 실수로 들어와도 자기 자신으로 무한 리다이렉트하지 않도록 아래에서 뺀다.
LEGACY_HOSTS = {
    h.strip().lower()
    for h in (os.getenv("LEGACY_HOSTS") or "").split(",")
    if h.strip()
} - {CANONICAL_HOST, "www." + CANONICAL_HOST}


def _visitor_scheme(request: Request) -> str:
    """방문자↔앞단 구간의 프로토콜. 알 수 없으면 빈 문자열.

    앞단이 두 겹이라 헤더 하나로는 알 수 없다.

        방문자 ──https──> Cloudflare ──http──> 카페24 엣지 ──> 이 앱

    카페24 엣지는 **자기가 받은** 프로토콜로 X-Forwarded-Proto 를
    덮어쓴다(실측 확인). Cloudflare 를 Flexible 로 두면 그 구간이 http 라
    엣지는 늘 `http` 를 적어 준다. 그걸 믿고 방문자를 https 로 돌려보내면
    그 요청이 또 http 로 원본에 닿아 **무한 리다이렉트**가 된다.

    그래서 Cloudflare 가 붙이는 CF-Visitor 를 먼저 본다. 이건 방문자↔
    Cloudflare 구간의 프로토콜이라 우리가 알고 싶은 바로 그 값이고,
    Cloudflare 는 클라이언트가 보낸 CF-* 헤더를 버리고 자기 값으로 새로
    쓴다. Cloudflare 를 거치지 않는 직접 접속에는 이 헤더가 없으므로
    그때는 예전처럼 X-Forwarded-Proto 로 떨어진다.

    둘 다 없으면 빈 문자열을 돌려준다 — 판단할 근거가 없을 때는
    건드리지 않는 쪽이 안전하다.
    """
    cf = request.headers.get("cf-visitor") or ""
    if cf:
        # 형식은 {"scheme":"https"}. 남이 보낸 값일 수도 있으니 깨져 있어도
        # 그냥 다음 헤더로 넘어간다.
        try:
            scheme = (json.loads(cf).get("scheme") or "").strip().lower()
        except Exception:
            scheme = ""
        if scheme in ("http", "https"):
            return scheme
    return (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()


@app.middleware("http")
async def canonical_redirect(request: Request, call_next):
    proto = _visitor_scheme(request)
    host = (request.headers.get("host") or "").split(":")[0].lower()

    def _to(base: str):
        target = base + request.url.path
        if request.url.query:
            target += "?" + request.url.query
        # 301: 검색엔진이 색인을 옮기도록. 주소 정책은 되돌릴 일이 없다.
        return RedirectResponse(target, status_code=301)

    # 옛 도메인으로 들어온 요청 — 경로째로 새 도메인에 넘긴다.
    # 프로토콜은 따지지 않는다. 어차피 목적지가 https 라서 한 번에 끝난다.
    if host in LEGACY_HOSTS:
        return _to(SITE_URL)

    # 운영 도메인이 아닐 때(로컬, 카페24 컨테이너 주소, 헬스체크)는 그대로 둔다.
    if host not in (CANONICAL_HOST, "www." + CANONICAL_HOST):
        return await call_next(request)

    need_https = proto == "http"          # 헤더가 없으면 False — 손대지 않는다
    need_apex = host.startswith("www.")
    if need_https or need_apex:
        return _to("https://" + CANONICAL_HOST)

    return await call_next(request)


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
# 어드민 통계. design.router(캐치올 성격의 페이지 라우트)보다 먼저 등록해야
# /api/admin/stats/* 가 정적 파일 서빙으로 새지 않는다.
app.include_router(stats.router)
# wisefont / design / use 라우터는 catch-all(/{full_path:path})보다 반드시 먼저 등록해야
# /wisefont/{slug}, /design/{id}, /use/{slug}, /find-font 요청이 catch-all에 가로채이지 않는다.
app.include_router(wisefont.router)
app.include_router(use_case_route.router)
# 매거진 — /about.html 301 이 여기 들어 있어 정적 catch-all 보다 먼저 등록해야 한다.
app.include_router(magazine.router)
app.include_router(gif.router)
app.include_router(design.router)


# 헬스체크 — DB 종류와 경로/호스트도 함께 노출 (운영 데이터 보존 진단용)
@app.get("/api/health")
def health(request: Request):
    """기본 헬스 + DB 연결 상태 + 폰트/태그 카운트 + DB 종류

    canonical_redirect 가 제대로 판단하는지 보려면 proxy 항목을 확인한다.
    visitor_scheme 이 실제로 쓰이는 값이다. 이게 빈 값이면 프로토콜을
    알려 주는 앞단이 없다는 뜻이고, 그때는 http→https 리다이렉트가
    (안전하게) 동작하지 않는다.

    Cloudflare 를 앞에 세운 뒤에는 cf_visitor 가 {"scheme":"https"} 로,
    visitor_scheme 이 https 로 찍혀야 한다. x_forwarded_proto 는 그때
    http 로 남는데(Cloudflare→카페24 구간이 http 라서) 정상이다.
    cf_connecting_ip 가 채워지면 Cloudflare 를 거쳐 들어온 요청이다."""
    info = {"status": "ok", "service": "freefontpick-api", "version": "1.0.0"}
    info["proxy"] = {
        "host": request.headers.get("host"),
        "visitor_scheme": _visitor_scheme(request),
        "cf_visitor": request.headers.get("cf-visitor"),
        "cf_connecting_ip": request.headers.get("cf-connecting-ip"),
        "x_forwarded_proto": request.headers.get("x-forwarded-proto"),
        "x_forwarded_host": request.headers.get("x-forwarded-host"),
        "x_forwarded_for": request.headers.get("x-forwarded-for"),
    }
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


# 서버가 마커를 채워야 완성되는 템플릿. 직접 주소로 열면 {{FFP_TITLE}} 같은
# 마커가 그대로 보이는 깨진 페이지가 나가고, canonical 도 "{{FFP_CANONICAL}}"
# 이라 정식 주소로 모아 주지도 못한다. 색인 허용 상태라 그대로 두면 검색에
# 걸릴 수 있으므로 없는 주소로 취급한다.
#
# 라우트는 이 파일들을 디스크에서 직접 읽으므로(FONT_PAGE_PATH 등) 여기서
# 막아도 정상 페이지에는 영향이 없다.
SSR_ONLY_TEMPLATES = {
    "font.html", "use.html", "wisefont.html", "font-pair.html",
    "gif-templates.html", "magazine.html", "about.html",
}


def _static_not_found(request: Request):
    """정적 경로에서 못 찾았을 때.

    브라우저에는 404 페이지를, 그 밖(API 클라이언트·크롤러의 자산 요청 등)
    에는 기존처럼 JSON 을 준다. 어느 쪽이든 상태 코드는 404 다."""
    if "text/html" in (request.headers.get("accept") or ""):
        return not_found_page()
    return JSONResponse({"detail": "Not Found"}, status_code=404)


@app.get("/{full_path:path}")
async def serve_static(full_path: str, request: Request):
    """루트의 모든 경로 → static/ 폴더의 파일로 서빙

    - / → static/index.html
    - /admin.html → static/admin.html
    - /logo.png → static/logo.png
    """
    # 빈 경로는 index
    if not full_path or full_path == "/":
        target = STATIC_DIR / "index.html"
    else:
        if full_path.strip("/").lower() in SSR_ONLY_TEMPLATES:
            return _static_not_found(request)
        target = STATIC_DIR / full_path

    # 디렉토리 traversal 방지
    try:
        target = target.resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())):
            return _static_not_found(request)
    except Exception:
        return _static_not_found(request)

    if not target.exists() or not target.is_file():
        return _static_not_found(request)

    # HTML 은 공유 헤더·푸터를 넣어서 내보낸다. 이 길로 나가는 페이지가
    # 약관·개인정보처리방침인데, 라우터를 거치지 않는다는 이유로 이 둘만
    # 예전 푸터를 달고 있었다 — 회사 정보도 약관 링크도 없는 짧은 판이었다.
    #
    # 마커가 없는 파일에는 아무 일도 일어나지 않는다(문자열 치환일 뿐이다).
    # 관리자 페이지처럼 마커를 안 쓰는 파일은 그대로 나간다.
    if target.suffix.lower() == ".html":
        try:
            return HTMLResponse(inject_header(target.read_text(encoding="utf-8")))
        except OSError:
            return _static_not_found(request)

    return FileResponse(target)
