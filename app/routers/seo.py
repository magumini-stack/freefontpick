"""SEO 라우터 — sitemap.xml + robots.txt + 디버그 엔드포인트"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Request, Depends
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Font


router = APIRouter(tags=["seo"])

SITE_URL = os.getenv("SITE_URL", "https://freefontpick.co.kr").rstrip("/")


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(db: Session = Depends(get_db)):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    pages = [
        {"loc": f"{SITE_URL}/", "priority": "1.0", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/find-font", "priority": "0.7", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/#notice", "priority": "0.6", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/about.html", "priority": "0.5", "changefreq": "monthly"},
        {"loc": f"{SITE_URL}/faq.html", "priority": "0.5", "changefreq": "monthly"},
        # GIF 생성기는 페이지 2개뿐이다. 템플릿별 URL을 만들지 않은 이유는
        # gif.py 주석 참고 — 페이로드만 다른 페이지 48개는 중복 색인 판정을 부른다.
        # 템플릿 목록이 위다 — 헤더 메뉴도 여기로 보내는 대표 페이지이고,
        # 빈 편집기보다 '무엇을 만들 수 있는지'가 검색 결과에 더 맞는다.
        {"loc": f"{SITE_URL}/gif/templates", "priority": "0.8", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/gif", "priority": "0.7", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/policy.html", "priority": "0.3", "changefreq": "yearly"},
    ]
    # 폰트별 상세페이지 (핵심 SEO 자산)
    # 2026-07: /design/{id}는 /font/{id}의 canonical 페이지이므로 sitemap에서 제외.
    # canonical이 아닌 URL을 sitemap에 올리면 구글에게 엇갈린 신호를 줘서
    # 중복 색인 판단을 더 헷갈리게 만든다 (/font/ 색인 누락의 원인 중 하나였음).
    try:
        fonts = db.query(Font.id).all()
        for (fid,) in fonts:
            pages.append({
                "loc": f"{SITE_URL}/font/{fid}",
                "priority": "0.9",
                "changefreq": "monthly",
            })
    except Exception:
        # DB 접근 실패해도 sitemap은 정적 페이지만이라도 반환
        pass

    # (주)와이즈폰트 자사 폰트 배포 페이지 (/wisefont/{slug})
    # 목록을 여기서 다시 적지 않고 라우터에서 가져와야, 폰트를 추가·삭제할 때
    # sitemap이 자동으로 따라온다. 두 곳에 나눠 적으면 반드시 어긋난다.
    try:
        from .wisefont import WISEFONTS
        for wf in WISEFONTS:
            pages.append({
                "loc": f"{SITE_URL}/wisefont/{wf['slug']}",
                "priority": "0.8",
                "changefreq": "monthly",
            })
    except Exception:
        pass

    # 용도 허브 (/use/{slug}) — 검색 진입을 노리는 핵심 랜딩 페이지
    # 허브 목록은 DB에서 읽는다. 여기에 slug를 다시 적어두면 어드민에서
    # 허브를 켜고 끌 때 sitemap이 어긋난다.
    try:
        from ..models import UseCase
        for (uslug,) in db.query(UseCase.slug).filter(UseCase.is_active.is_(True)).all():
            pages.append({
                "loc": f"{SITE_URL}/use/{uslug}",
                "priority": "0.9",
                "changefreq": "weekly",
            })
    except Exception:
        pass

    items = "\n".join(
        f"  <url>\n    <loc>{p['loc']}</loc>\n    <lastmod>{today}</lastmod>\n"
        f"    <changefreq>{p['changefreq']}</changefreq>\n    <priority>{p['priority']}</priority>\n  </url>"
        for p in pages
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items}\n</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/robots.txt", include_in_schema=False)
def robots():
    body = (
        "User-agent: *\nAllow: /\nDisallow: /admin.html\nDisallow: /admin/gif\n"
        "Disallow: /api/auth/\nDisallow: /api/fonts/*/file\n"
        "Disallow: /api/fonts/*/like\n\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    return Response(content=body, media_type="text/plain",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/api/debug/upload-env", include_in_schema=False)
def debug_upload_env():
    info = {"python_version": sys.version, "cwd": str(Path.cwd())}
    try:
        from .files import FONTS_DIR, BUNDLED_FONTS_DIR
        info["fonts_dir"] = str(FONTS_DIR)
        info["fonts_dir_exists"] = FONTS_DIR.exists()
        info["bundled_fonts_dir"] = str(BUNDLED_FONTS_DIR)
        info["bundled_fonts_dir_exists"] = BUNDLED_FONTS_DIR.exists()
        if BUNDLED_FONTS_DIR.exists():
            files = list(BUNDLED_FONTS_DIR.iterdir())
            info["bundled_count"] = len(files)
        test = FONTS_DIR / ".write_test"
        try:
            FONTS_DIR.mkdir(parents=True, exist_ok=True)
            test.write_text("ok")
            test.unlink()
            info["fonts_dir_writable"] = True
        except Exception as e:
            info["fonts_dir_writable"] = False
            info["fonts_dir_write_error"] = str(e)
    except Exception as e:
        info["files_import_error"] = str(e)

    for mod_name in ["fontTools", "brotli", "multipart"]:
        try:
            __import__(mod_name)
            info[mod_name] = "ok"
        except Exception as e:
            info[f"{mod_name}_error"] = str(e)

    try:
        ud = Path("/app/user_data")
        if ud.exists():
            info["app_user_data_contents"] = [p.name for p in list(ud.iterdir())[:20]]
            fonts_in_ud = ud / "fonts"
            if fonts_in_ud.exists():
                files = list(fonts_in_ud.iterdir())
                info["user_data_fonts_count"] = len(files)
    except Exception as e:
        info["app_user_data_error"] = str(e)

    # 메모리 정보
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        info["max_rss_kb"] = usage.ru_maxrss
    except Exception as e:
        info["mem_error"] = str(e)

    return JSONResponse(content=info)


@router.post("/api/debug/upload-echo", include_in_schema=False)
async def debug_upload_echo(request: Request):
    """파일을 받기만 하고 메모리에 로드 안 함. multipart 파싱이 가능한지만 확인.

    이게 통과하면 → uvicorn/multipart는 OK, 우리 변환 코드가 OOM 유발
    이게 실패하면 → uvicorn/nginx 단계에서 막힘
    """
    info = {"steps": []}
    try:
        # Content-Length만 확인 (본문은 안 읽음)
        cl = request.headers.get("content-length", "?")
        info["steps"].append(f"content-length header: {cl}")
        info["headers"] = dict(request.headers)
    except Exception as e:
        info["steps"].append(f"header read FAILED: {e}")
        info["traceback"] = traceback.format_exc()
        return JSONResponse(content=info, status_code=200)

    try:
        # 본문을 청크 단위로 읽기만 하고 버림 (메모리 소비 안 함)
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
        info["steps"].append(f"streamed bytes: {total}")
        info["bytes_received"] = total
        return JSONResponse(content=info, status_code=200)
    except Exception as e:
        info["steps"].append(f"stream FAILED: {type(e).__name__}: {e}")
        info["traceback"] = traceback.format_exc()
        return JSONResponse(content=info, status_code=200)
