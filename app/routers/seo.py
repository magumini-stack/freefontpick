"""SEO 라우터 — sitemap.xml + robots.txt 동적 생성

검색 엔진(구글, 네이버 등)이 사이트 구조를 파악할 수 있도록
표준 형식의 sitemap.xml과 robots.txt를 제공한다.

기본 도메인은 SITE_URL 환경변수 또는 https://freefontpick.co.kr
"""
import os
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import Response


router = APIRouter(tags=["seo"])

# 정식 도메인 — 환경변수로 오버라이드 가능
SITE_URL = os.getenv("SITE_URL", "https://freefontpick.co.kr").rstrip("/")


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    """검색 엔진용 사이트맵.

    공개 페이지만 포함:
    - 메인 (/)
    - 공지사항 목록 (#notice)
    - 이용약관 (/policy.html)
    - 개인정보처리방침 (/privacy.html)

    폰트별 페이지는 별도 URL이 아니므로 포함하지 않음 (해시 기반 검색).
    """
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
    """검색 엔진 크롤러 규칙.

    - 정적 페이지는 모두 허용
    - 어드민, 인증 API, 좋아요 API는 차단
    - sitemap.xml 위치 명시
    """
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
