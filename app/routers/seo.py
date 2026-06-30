"""SEO 라우터 — sitemap.xml + robots.txt + 디버그 엔드포인트"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Request
from fastapi.responses import Response, JSONResponse


router = APIRouter(tags=["seo"])

SITE_URL = os.getenv("SITE_URL", "https://freefontpick.co.kr").rstrip("/")


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    pages = [
        {"loc": f"{SITE_URL}/", "priority": "1.0", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/#notice", "priority": "0.7", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/policy.html", "priority": "0.3", "changefreq": "yearly"},
        {"loc": f"{SITE_URL}/privacy.html", "priority": "0.3", "changefreq": "yearly"},
    ]
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
        "User-agent: *\nAllow: /\nDisallow: /admin.html\n"
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


@router.post("/api/debug/upload-direct", include_in_schema=False)
async def debug_upload_direct(file: UploadFile = File(...)):
    """파일을 직접 받아서 우리 변환 코드를 단계별로 실행."""
    info = {"filename": file.filename, "steps": []}

    try:
        content = await file.read()
        info["steps"].append(f"read: {len(content)} bytes")
    except Exception as e:
        info["steps"].append(f"read FAILED: {type(e).__name__}: {e}")
        info["traceback"] = traceback.format_exc()
        return JSONResponse(content=info, status_code=200)

    try:
        from ..subset import subset_font_bytes
        woff2_bytes, sub_info = subset_font_bytes(content, is_english=False)
        info["steps"].append(f"subset OK: {len(woff2_bytes)} bytes")
        info["method"] = "subset"
        return JSONResponse(content=info, status_code=200)
    except Exception as e:
        info["steps"].append(f"subset FAILED: {type(e).__name__}: {e}")
        info["subset_traceback"] = traceback.format_exc()

    try:
        from ..subset import convert_to_woff2_no_subset
        woff2_bytes = convert_to_woff2_no_subset(content)
        info["steps"].append(f"convert_only OK: {len(woff2_bytes)} bytes")
        info["method"] = "convert_only"
        return JSONResponse(content=info, status_code=200)
    except Exception as e:
        info["steps"].append(f"convert_only FAILED: {type(e).__name__}: {e}")
        info["convert_traceback"] = traceback.format_exc()

    info["method"] = "all_failed"
    return JSONResponse(content=info, status_code=200)
