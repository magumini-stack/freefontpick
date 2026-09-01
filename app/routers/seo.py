"""SEO 라우터 — sitemap.xml + robots.txt + 디버그 엔드포인트"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Font


router = APIRouter(tags=["seo"])

from ..site import SITE_URL


def _x(s) -> str:
    """XML 특수문자 이스케이프. 폰트 이름에 & 하나만 들어와도
    sitemap 전체가 파싱 불가가 되므로 반드시 거친다."""
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(db: Session = Depends(get_db)):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    pages = [
        {"loc": f"{SITE_URL}/", "priority": "1.0", "changefreq": "weekly"},
        # /find-font 는 아래에서 답변 글이 얼마나 쌓였는지 보고 넣는다 —
        # 읽을 글이 없는 게시판을 검색엔진에 먼저 알릴 이유가 없다.
        # /#notice 는 뺐다. 조각(#)은 구글이 무시하므로 "/" 와 같은 URL 로 취급되고,
        # 사이트맵에 중복 URL 을 올리면 색인 판단만 헷갈리게 만든다.
        {"loc": f"{SITE_URL}/magazine", "priority": "0.8", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/about", "priority": "0.5", "changefreq": "monthly"},
        {"loc": f"{SITE_URL}/faq.html", "priority": "0.5", "changefreq": "monthly"},
        # GIF 생성기는 페이지 2개뿐이다. 템플릿별 URL을 만들지 않은 이유는
        # gif.py 주석 참고 — 페이로드만 다른 페이지 48개는 중복 색인 판정을 부른다.
        # 템플릿 목록이 위다 — 헤더 메뉴도 여기로 보내는 대표 페이지이고,
        # 빈 편집기보다 '무엇을 만들 수 있는지'가 검색 결과에 더 맞는다.
        {"loc": f"{SITE_URL}/gif/templates", "priority": "0.8", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/gif", "priority": "0.7", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/policy.html", "priority": "0.3", "changefreq": "yearly"},
        # 개인정보처리방침은 광고 심사에서 실제로 확인하는 문서다. 푸터에만
        # 걸려 있고 사이트맵에는 빠져 있었다.
        {"loc": f"{SITE_URL}/privacy.html", "priority": "0.3", "changefreq": "yearly"},
    ]

    # 폰트 찾기 게시판 — design.py 와 같은 기준으로 판단한다. 두 곳이 어긋나면
    # 사이트맵은 올리라 하고 페이지는 noindex 인 모순이 생긴다.
    try:
        from ..models import SubmissionAnswer
        from .design import FIND_FONT_INDEX_MIN
        if db.query(SubmissionAnswer).count() >= FIND_FONT_INDEX_MIN:
            pages.append({"loc": f"{SITE_URL}/find-font",
                          "priority": "0.7", "changefreq": "weekly"})
    except Exception:
        pass
    # 매거진 글. 목록에서 코드로 읽어 온다 — 글을 추가할 때 sitemap 을 따로
    # 고쳐야 하면 반드시 한쪽이 빠진다.
    try:
        from ..magazine import POSTS, image_src
        for post in POSTS:
            page = {
                "loc": f"{SITE_URL}/magazine/{post['slug']}",
                "priority": "0.7",
                "changefreq": "monthly",
            }
            src = image_src(post)
            if src:
                page["image"] = {
                    "loc": SITE_URL + src,
                    "title": post["title"],
                }
            pages.append(page)
    except Exception:
        pass

    # 폰트별 상세페이지 (핵심 SEO 자산)
    # 2026-07: /design/{id}는 /font/{id}의 canonical 페이지이므로 sitemap에서 제외.
    # canonical이 아닌 URL을 sitemap에 올리면 구글에게 엇갈린 신호를 줘서
    # 중복 색인 판단을 더 헷갈리게 만든다 (/font/ 색인 누락의 원인 중 하나였음).
    try:
        from .sample_image import has_sample, sample_version

        fonts = db.query(Font.id, Font.name).all()
        for fid, fname in fonts:
            page = {
                "loc": f"{SITE_URL}/font/{fid}",
                "priority": "0.9",
                "changefreq": "monthly",
            }
            if has_sample(fid):
                page["image"] = {
                    "loc": f"{SITE_URL}/api/fonts/{fid}/sample-image?v={sample_version(fid)}",
                    "title": f"무료폰트 {fname} 활용 예시",
                }
            pages.append(page)
    except Exception:
        # DB 접근 실패해도 sitemap은 정적 페이지만이라도 반환
        pass

    # (주)와이즈폰트 자사 폰트 배포 페이지 (/wisefont/{slug})는 sitemap에서 뺐다.
    #
    # 이 14개 URL은 canonical이 /font/{id}를 가리킨다 — 상세페이지와 내용이
    # 겹쳐서 대표 URL을 그쪽으로 몰아준 것이다. 그런데 sitemap에는 그대로
    # 올라가 있었다. 사이트맵은 "이걸 색인해라", canonical은 "아니다, 저걸
    # 봐라"라고 서로 다른 말을 하는 꼴이라 구글에게 엇갈린 신호가 된다.
    # 바로 위 /design/{id}를 뺀 것과 같은 이유다.
    #
    # 페이지 자체는 그대로 살아 있고 링크로도 들어갈 수 있다. 다만 검색엔진에
    # 우리가 먼저 알리는 목록에서 빠질 뿐이다.

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

    def _one(p):
        out = (
            f"  <url>\n    <loc>{p['loc']}</loc>\n    <lastmod>{today}</lastmod>\n"
            f"    <changefreq>{p['changefreq']}</changefreq>\n"
            f"    <priority>{p['priority']}</priority>\n"
        )
        # 활용 예시 이미지가 있으면 이미지 사이트맵으로도 알린다. 페이지 안에
        # <img>로 들어 있어도, 여기 적어 두면 이미지 검색이 훨씬 빨리 집는다.
        img = p.get("image")
        if img:
            out += (
                "    <image:image>\n"
                f"      <image:loc>{_x(img['loc'])}</image:loc>\n"
                f"      <image:title>{_x(img['title'])}</image:title>\n"
                "    </image:image>\n"
            )
        return out + "  </url>"

    items = "\n".join(_one(p) for p in pages)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
        f"{items}\n</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})


# 해지한 애드센스 게시자 ID. 이 문자열이 든 ads.txt는 내보내지 않는다.
RETIRED_ADS_PUBLISHER = "pub-3337261318293302"
ADS_TXT_PATH = Path(__file__).resolve().parent.parent.parent / "static" / "ads.txt"


@router.get("/ads.txt", include_in_schema=False)
def ads_txt():
    """옛 게시자 ID가 든 ads.txt만 막고, 새 파일은 그대로 서빙한다.

    저장소에서 static/ads.txt를 지웠는데도 운영에서 계속 나갔다 —
    배포가 파일을 덮어쓰기만 하고 '없어진 파일'은 지우지 않기 때문이다.
    (컨테이너에 예전 파일이 남아 해지한 광고주 ID를 계속 노출하고 있었다.)
    카페24 쪽에 파일을 지우는 수단이 없어서 이 라우트로 끊는다 —
    catch-all보다 먼저 잡힌다.

    광고는 계속 하고 계정만 바꾸실 예정이므로, 무조건 404를 내면 안 된다.
    새 계정 ads.txt를 올리는 순간 애드센스가 '파일 없음'으로 보고 수익을
    제한하기 때문이다. 그래서 '파일이 있는가'가 아니라 '옛 ID가 들어
    있는가'로 판단한다. 새 ads.txt를 저장소에 넣고 배포하면 배포가
    낡은 파일을 덮어쓰고, 이 라우트는 그대로 통과시킨다 — 코드를 다시
    고칠 필요가 없다. (새 ID를 받으면 위 상수는 지워도 된다.)
    """
    try:
        body = ADS_TXT_PATH.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(status_code=404)
    if RETIRED_ADS_PUBLISHER in body:
        raise HTTPException(status_code=404)
    return Response(content=body, media_type="text/plain",
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


@router.get("/api/debug/subset", include_in_schema=False)
def debug_subset():
    """미리보기 서브셋이 만들어지고 있는지 들여다본다.

    운영에서 앱 로그를 볼 수 없어서, 실패 사유를 여기로 끌어낸다.
    문제가 정리되면 이 엔드포인트는 지운다.
    """
    from ..font_subset import status
    return status()


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
