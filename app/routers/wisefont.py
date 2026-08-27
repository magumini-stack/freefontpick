"""(주)와이즈폰트 자사 폰트 배포 페이지 — 폰트 1종당 페이지 1개.

  GET  /wisefont/{slug}                  → 배포 페이지 (static/wisefont.html 템플릿)
  GET  /api/wisefont/{slug}/download     → 폰트 zip 다운로드

폰트 파일을 static/ 아래가 아니라 저장소 루트의 fontfiles/ 에 두는 이유:
static은 통째로 마운트되어 있어서 파일 URL을 아는 사람은 페이지를 거치지 않고
바로 받을 수 있다. 그러면 "폰트픽에서만 다운로드"라는 라이선스 고지가 기술적으로
무의미해지고, 다운로드 집계도 불가능하다. fontfiles/ 는 마운트하지 않고
아래 엔드포인트를 통해서만 내보낸다.

폰트 목록은 14종 내외로 거의 바뀌지 않으므로 DB 테이블 대신 이 파일의
WISEFONTS 리스트로 관리한다. 배포와 함께 버전 관리되고, import 시점에
검증되므로 오타가 런타임까지 흘러가지 않는다.
"""
import json
import re
from pathlib import Path

from urllib.parse import quote as _q
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ..header import inject_header, not_found_page

router = APIRouter(tags=["wisefont"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = BASE_DIR / "static"
FONTFILES_DIR = BASE_DIR / "fontfiles"
TEMPLATE_PATH = STATIC_DIR / "wisefont.html"

BASE_URL = "https://freefontpick.co.kr"
MAKER = "(주)와이즈폰트"

# ── 배포 폰트 목록 ────────────────────────────────────────────────
# slug      : URL과 파일명에 쓰는 영문 식별자 (파일은 fontfiles/{slug}.zip)
# name      : 화면에 크게 노출되는 폰트 이름
# full_name : 폰트 영문 정식명(폰트 파일 내부 이름)
# ko_full   : 폰트 한글 정식명 — 사용자가 내려받을 때의 파일명으로 쓴다
# formats   : 동봉된 파일 형식
# weights   : 굵기 구성
# glyphs    : 수록 글자 수
# tags      : 분류 태그
# font_id   : 폰트픽 상세페이지 id (있으면 상호 링크, 없으면 None)
WISEFONTS = [
    {
        "slug": "cutedoggy",
        "ko_full": "TDTD귀욤뭉이",
        "name": "귀욤뭉이",
        "full_name": "TDTDCuteDoggy",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["손글씨", "귀여운"],
        "font_id": None,
    },
    {
        "slug": "fernlove",
        "ko_full": "TDTD고사리사랑",
        "name": "고사리사랑",
        "full_name": "TDTDFernLove",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["펜시", "감성"],
        "font_id": None,
    },
    {
        "slug": "fullofclouds",
        "ko_full": "TDTD구름가득",
        "name": "구름가득",
        "full_name": "TDTDFullofClouds",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["펜시", "부드러운"],
        "font_id": None,
    },
    {
        "slug": "godofmusic",
        "ko_full": "TDTD음악의신",
        "name": "음악의신",
        "full_name": "TDTDGodofMusic",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["펜시", "리듬감"],
        "font_id": None,
    },
    {
        "slug": "hiphop",
        "ko_full": "TDTD힙합",
        "name": "힙합",
        "full_name": "TDTDHiphop",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["펜시", "개성"],
        "font_id": None,
    },
    {
        "slug": "lovemetender",
        "ko_full": "TDTD러브미텐더",
        "name": "러브미텐더",
        "full_name": "TDTDLoveMeTender",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["펜시", "레트로"],
        "font_id": None,
    },
    {
        "slug": "photogon",
        "ko_full": "TDTD사진관",
        "name": "사진관",
        "full_name": "TDTDPhotogon",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["손글씨", "레트로"],
        "font_id": None,
    },
    {
        "slug": "poodle",
        "ko_full": "TDTD푸들",
        "name": "푸들",
        "full_name": "TDTDPoodle",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["펜시", "섬세한"],
        "font_id": None,
    },
    {
        "slug": "rightlife",
        "ko_full": "TDTD바른생활",
        "name": "바른생활",
        "full_name": "TDTDRightLife",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["손글씨", "단정한"],
        "font_id": None,
    },
    {
        "slug": "seoulro",
        "ko_full": "TDTD서울로",
        "name": "서울로",
        "full_name": "TDTDSeoulRo",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["제목용", "굵은"],
        "font_id": None,
    },
    {
        "slug": "starlightnight",
        "ko_full": "TDTD별헤는밤",
        "name": "별헤는밤",
        "full_name": "TDTDStarlightNight",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["펜시", "감성"],
        "font_id": None,
    },
    {
        "slug": "tadaktadak",
        "ko_full": "TDTD타닥타닥",
        "name": "타닥타닥",
        "full_name": "TDTDTadakTadak",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["손글씨", "따뜻한"],
        "font_id": None,
    },
    {
        "slug": "tuntuni",
        "ko_full": "TDTD뚠뚠이",
        "name": "뚠뚠이",
        "full_name": "TDTDTuntuni",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 2,574자 (상용 글자 중심)",
        "tags": ["제목용", "통통한"],
        "font_id": None,
    },
    {
        "slug": "emotionmj",
        "ko_full": "TDTD갬성명조",
        "name": "갬성명조",
        "full_name": "TDTDEmotionMj",
        "formats": "TTF, OTF",
        "weights": "1종 Regular",
        "glyphs": "완성형 11,172자",
        "tags": ["명조", "감성"],
        "font_id": None,
    },
]

_BY_SLUG = {f["slug"]: f for f in WISEFONTS}

# slug 형식 검증 — 경로 탈출(../) 등을 원천 차단
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}$")
for _f in WISEFONTS:
    if not _SLUG_RE.match(_f["slug"]):
        raise ValueError(f"잘못된 wisefont slug: {_f['slug']!r}")


def _esc(s: str) -> str:
    import html as _h
    return _h.escape(str(s or ""))


def _thumb_url(slug: str) -> str:
    return f"/static/fontthumb/{slug}.jpg"


@router.get("/wisefont/{slug}", response_class=HTMLResponse)
def wisefont_page(slug: str):
    font = _BY_SLUG.get(slug)
    if font is None:
        return not_found_page()

    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = inject_header(html, "")

    name = font["name"]
    url = f"{BASE_URL}/wisefont/{slug}"
    thumb = f"{BASE_URL}{_thumb_url(slug)}"
    title = f"{name} 무료 다운로드 ({font['formats'].replace(', ', '·')}) - {MAKER} 공식 배포 | 폰트픽"
    desc = (
        f"{name}은(는) 폰트 구독서비스 타닥타닥을 운영하는 {MAKER}가 제작·배포하는 "
        f"무료 한글 폰트입니다. {font['formats']}를 폰트픽에서 내려받으세요."
    )

    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "description": desc,
        "url": url,
        "inLanguage": "ko",
        "isPartOf": {"@type": "WebSite", "name": "폰트픽", "url": BASE_URL},
        "primaryImageOfPage": {"@type": "ImageObject", "url": thumb},
        "mainEntity": {
            "@type": "CreativeWork",
            "name": font["full_name"],
            "creator": {"@type": "Organization", "name": MAKER},
            "keywords": ", ".join(font["tags"]),
        },
    }, ensure_ascii=False)

    spec_rows = "".join(
        f'<li><span class="k">{_esc(k)}</span><span class="v">{_esc(v)}</span></li>'
        for k, v in [
            ("파일 형식", font["formats"]),
            ("굵기", font["weights"]),
            ("글자 수", font["glyphs"]),
            ("분류", " · ".join(font["tags"])),
        ]
    )

    detail_link = ""
    if font.get("font_id"):
        detail_link = (
            f'<p class="detail-link">'
            f'<a href="/font/{font["font_id"]}">{_esc(name)} 상세 정보 보기</a></p>'
        )

    repl = {
        "{{WF_TITLE}}": _esc(title),
        "{{WF_DESC}}": _esc(desc),
        "{{WF_CANONICAL}}": url,
        "{{WF_OG_IMAGE}}": thumb,
        "{{WF_JSONLD}}": f'<script type="application/ld+json">{json_ld}</script>',
        "{{WF_NAME}}": _esc(name),
        # mailto 주소에 들어갈 폰트명은 HTML 이스케이프가 아니라 URL 인코딩이 필요하다.
        # "카페 24 쑥쑥"처럼 공백이 있으면 주소가 거기서 끊겨 제목이 잘린다.
        "{{WF_NAME_URL}}": _q(name),
        "{{WF_FULLNAME}}": _esc(font["full_name"]),
        "{{WF_FORMATS}}": _esc(font["formats"]),
        "{{WF_SPECS}}": spec_rows,
        "{{WF_THUMB}}": _thumb_url(slug),
        "{{WF_SLUG}}": slug,
        "{{WF_DETAIL_LINK}}": detail_link,
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    return HTMLResponse(html)


@router.get("/api/wisefont/{slug}/download")
def wisefont_download(slug: str):
    """폰트 zip 전달.

    FileResponse는 파일을 통째로 메모리에 올리지 않고 스트리밍하므로,
    큰 파일이어도 워커 메모리를 점유하지 않는다.
    """
    font = _BY_SLUG.get(slug)
    if font is None:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    path = (FONTFILES_DIR / f"{slug}.zip").resolve()
    # 심볼릭 링크 등으로 fontfiles 밖을 가리키지 않는지 최종 확인
    if FONTFILES_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="폰트 파일을 찾을 수 없습니다")

    return FileResponse(
        path,
        media_type="application/zip",
        # 한글 파일명은 Starlette가 RFC 5987(filename*)로 안전하게 인코딩해준다
        filename=f"{font['ko_full']}.zip",
        headers={"Cache-Control": "public, max-age=3600"},
    )
