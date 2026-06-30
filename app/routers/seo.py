"""SEO 라우터 — sitemap.xml + robots.txt 동적 생성

검색 엔진(구글, 네이버 등)이 사이트 구조를 파악할 수 있도록
표준 형식의 sitemap.xml과 robots.txt를 제공한다.

기본 도메인은 SITE_URL 환경변수 또는 https://freefontpick.co.kr
"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import Response, JSONResponse


router = APIRouter(tags=["seo"])

# 정식 도메인 — 환경변수로 오버라이드 가능
SITE_URL = os.getenv("SITE_URL", "https://freefontpick.co.kr").rstrip("/")


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    """검색 엔진용 사이트맵."""
    today = datetime.utcnow().strftime("%Y-%m-%d")

    pages = [
        {"loc": f"{SITE_URL}/", "priority": "1.0", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/#notice", "priority": "0.7", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/policy.html", "priority": "0.3", "changefreq": "yearly"},
        {"loc": f"{SITE_URL}/privacy.html", "priority": "0.3", "changefreq": "yearly"},
    ]

    items = "\n".join(
        f"  <url>\n"
        f"    <loc>{p['loc']}</loc>\n"
        f"    <lastmod>{today}</lastmod>\n"
        f"    <changefreq>{p['changefreq']}</changefreq>\n"
        f"    <priority>{p['priority']}</priority>\n"
        f"  </url>"
        for p in pages
    )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items}\n"
        "</urlset>\n"
    )

    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/robots.txt", include_in_schema=False)
def robots():
    """검색 엔진 크롤러 규칙."""
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin.html\n"
        "Disallow: /api/auth/\n"
        "Disallow: /api/fonts/*/file\n"
        "Disallow: /api/fonts/*/like\n"
        "\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    return Response(
        content=body,
        media_type="text/plain",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/api/debug/upload-env", include_in_schema=False)
def debug_upload_env():
    """폰트 업로드 파이프라인 진단 — 어떤 단계가 실패하는지 확인"""
    info = {"python_version": sys.version}

    # 1. 디스크 쓰기 권한 점검
    try:
        from .files import FONTS_DIR
        info["fonts_dir"] = str(FONTS_DIR)
        info["fonts_dir_exists"] = FONTS_DIR.exists()
        # 쓰기 테스트
        test_file = FONTS_DIR / ".write_test"
        try:
            FONTS_DIR.mkdir(parents=True, exist_ok=True)
            test_file.write_text("ok")
            test_file.unlink()
            info["fonts_dir_writable"] = True
        except Exception as e:
            info["fonts_dir_writable"] = False
            info["fonts_dir_write_error"] = str(e)
    except Exception as e:
        info["fonts_dir_check_error"] = str(e)

    # 2. fontTools 사용 가능?
    try:
        from fontTools.ttLib import TTFont
        from fontTools.subset import Subsetter
        info["fonttools"] = "ok"
    except Exception as e:
        info["fonttools_error"] = str(e)

    # 3. brotli (woff2 변환용)
    try:
        import brotli
        info["brotli"] = "ok"
    except ImportError:
        try:
            import Brotli
            info["brotli"] = "ok (Brotli)"
        except ImportError as e:
            info["brotli_error"] = str(e)

    # 4. python-multipart (FormData 받기용)
    try:
        import multipart
        info["python_multipart"] = "ok"
    except Exception as e:
        info["python_multipart_error"] = str(e)

    # 5. /app/user_data/ 폴더 점검
    try:
        ud = Path("/app/user_data")
        info["app_user_data_exists"] = ud.exists()
        if ud.exists():
            info["app_user_data_contents"] = [p.name for p in list(ud.iterdir())[:20]]
    except Exception as e:
        info["app_user_data_error"] = str(e)

    return JSONResponse(content=info)


@router.get("/api/debug/upload-test/{font_id}", include_in_schema=False)
def debug_upload_test(font_id: int):
    """실제 업로드 파이프라인을 점검 — 시드 폰트를 읽어서 변환 시도까지 해봄"""
    info = {"font_id": font_id, "steps": []}

    try:
        from .files import bundled_font_path, _process_font_bytes
        bp = bundled_font_path(font_id)
        info["steps"].append(f"bundled path: {bp}")
        info["steps"].append(f"exists: {bp.exists()}")
        if not bp.exists():
            return JSONResponse(content=info)

        # 시드 woff2 읽기
        content = bp.read_bytes()
        info["steps"].append(f"read {len(content)} bytes")

        # 변환 시도
        try:
            final_bytes, fmt_info, method = _process_font_bytes(content, False, "test.woff2")
            info["steps"].append(f"processed via {method}: {len(final_bytes)} bytes")
            info["method"] = method
            info["fmt_info"] = fmt_info
        except Exception as e:
            info["steps"].append(f"process FAILED: {type(e).__name__}: {e}")
            info["traceback"] = traceback.format_exc()

    except Exception as e:
        info["steps"].append(f"OUTER FAILED: {type(e).__name__}: {e}")
        info["traceback"] = traceback.format_exc()

    return JSONResponse(content=info)
