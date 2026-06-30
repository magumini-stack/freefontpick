"""SEO 라우터 — sitemap.xml + robots.txt 동적 생성 + 디버그"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, UploadFile, File
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

    # 1. /app/user_data/fonts 쓰기
    try:
        from .files import FONTS_DIR, BUNDLED_FONTS_DIR
        info["fonts_dir"] = str(FONTS_DIR)
        info["fonts_dir_exists"] = FONTS_DIR.exists()
        info["bundled_fonts_dir"] = str(BUNDLED_FONTS_DIR)
        info["bundled_fonts_dir_exists"] = BUNDLED_FONTS_DIR.exists()
        if BUNDLED_FONTS_DIR.exists():
            files = list(BUNDLED_FONTS_DIR.iterdir())
            info["bundled_count"] = len(files)
            info["bundled_sample"] = sorted([f.name for f in files])[:5]
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

    # 2. 패키지
    for mod_name in ["fontTools", "brotli", "multipart"]:
        try:
            __import__(mod_name)
            info[mod_name] = "ok"
        except Exception as e:
            info[f"{mod_name}_error"] = str(e)

    # 3. /app 전체 탐색
    try:
        app_dir = Path("/app")
        if app_dir.exists():
            info["app_contents"] = sorted([p.name for p in app_dir.iterdir()])
            # static 폴더 찾기
            for p in [app_dir / "static", app_dir / "static" / "fonts",
                      Path.cwd() / "static" / "fonts"]:
                key = f"check_{str(p).replace('/', '_')}"
                info[key] = {"path": str(p), "exists": p.exists()}
                if p.exists() and p.is_dir():
                    items = list(p.iterdir())
                    info[key]["count"] = len(items)
    except Exception as e:
        info["app_explore_error"] = str(e)

    # 4. user_data
    try:
        ud = Path("/app/user_data")
        if ud.exists():
            info["app_user_data_contents"] = [p.name for p in list(ud.iterdir())[:20]]
            fonts_in_ud = ud / "fonts"
            if fonts_in_ud.exists():
                files = list(fonts_in_ud.iterdir())
                info["user_data_fonts_count"] = len(files)
                info["user_data_fonts_sample"] = sorted([f.name for f in files])[:5]
    except Exception as e:
        info["app_user_data_error"] = str(e)

    return JSONResponse(content=info)


@router.post("/api/debug/upload-direct", include_in_schema=False)
async def debug_upload_direct(file: UploadFile = File(...)):
    """파일을 직접 받아서 우리 변환 코드를 단계별로 실행.

    인증 없이 호출 가능 (디버그용, 운영 안정화 후 제거 예정).
    어떤 단계에서 어떻게 실패하는지 traceback을 직접 보여줌.
    """
    info = {"filename": file.filename, "steps": []}

    # 1. 파일 읽기
    try:
        content = await file.read()
        info["steps"].append(f"read: {len(content)} bytes")
    except Exception as e:
        info["steps"].append(f"read FAILED: {type(e).__name__}: {e}")
        info["traceback"] = traceback.format_exc()
        return JSONResponse(content=info, status_code=200)

    # 2. 서브셋 변환
    try:
        from ..subset import subset_font_bytes
        woff2_bytes, sub_info = subset_font_bytes(content, is_english=False)
        info["steps"].append(f"subset OK: {len(woff2_bytes)} bytes ({sub_info})")
        info["method"] = "subset"
        return JSONResponse(content=info, status_code=200)
    except Exception as e:
        info["steps"].append(f"subset FAILED: {type(e).__name__}: {e}")
        info["subset_traceback"] = traceback.format_exc()

    # 3. convert_only fallback
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
