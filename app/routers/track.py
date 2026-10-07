"""클릭 기록 — 메인 4칸 메뉴 (2026-10-04) · 폰트 변환 받기 (10-06) · 타닥타닥 구독 배너 (10-07).

  POST /api/track/home-tool?tool=pair|find|convert|apps   (공개, 204)
  POST /api/track/convert?fmt=..&r=..                     (공개, 204)
  POST /api/track/tdtd-ad?spot=home|fonts                 (공개, 204)

사용자님이 "메인 4칸 메뉴 박스 클릭 수를 볼 수 있을까?" 하셔서 붙였다. 머리글 메뉴에도
같은 링크가 있어서 애널리틱스의 '다음 페이지'로는 4칸을 눌렀는지 메뉴를 눌렀는지 가를 수
없었다. 그래서 4칸만 따로 센다.

쌓는 곳은 페이지 조회와 같은 page_views 표다(kind='home_tool', key=칸 이름). 세는 규칙도
같다(app/font_views.py record_page) — 봇 UA 는 거르고, 같은 사람이 같은 칸을 30분 안에
다시 누르면 한 번으로 센다. 어드민 '통계' 탭이 /api/admin/stats/home-tools 로 읽는다.

화면(static/index.html)은 navigator.sendBeacon 으로 보낸다 — 페이지를 떠나는 순간에도
요청이 끝까지 가고, 이동을 기다리게 하지 않는다. 그래서 본문 없이 주소에 칸 이름만 싣는다.
"""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..font_views import record_page

router = APIRouter(tags=["track"])

# 칸 이름 → 화면 이름. 어드민 통계가 이 순서·이름으로 보여 준다(app/routers/stats.py).
# 2026-10-06 셋째 칸을 GIF 만들기 → 폰트 변환으로 바꿨다. 'gif' 는 지난 기록을 보이려고 맨 끝에 남긴다
# (캐시된 옛 메인에서 며칠 더 들어올 수도 있다).
HOME_TOOLS = {
    "pair": "폰트 조합 찾기",
    "find": "이미지로 폰트 찾기",
    "convert": "폰트 변환",
    "apps": "글자로 노는 앱",
    "gif": "GIF 만들기 (10/6까지)",
}


@router.post("/api/track/home-tool", include_in_schema=False)
def track_home_tool(request: Request, tool: str = "", db: Session = Depends(get_db)):
    if tool in HOME_TOOLS:
        try:
            record_page(request, "home_tool", tool, db)
        except Exception:
            pass
    return Response(status_code=204)


# 폰트 변환(/font-convert, 2026-10-06) 받기 — 단추를 눌러 파일을 받아 간 횟수.
# 변환은 브라우저 안에서만 하므로 서버가 아는 것은 이 신호뿐이다. 파일 이름·내용은 오지 않는다.
# key 는 '형식:범위'(예: woff2:web). 세는 규칙은 위와 같다(봇 제외, 30분 안 같은 받기는 한 번).
CONVERT_FORMATS = {"woff2", "woff", "ttf", "otf", "zip"}
CONVERT_RANGES = {"web", "k2780", "hangul", "all", "custom"}


@router.post("/api/track/convert", include_in_schema=False)
def track_convert(request: Request, fmt: str = "", r: str = "", db: Session = Depends(get_db)):
    if fmt in CONVERT_FORMATS:
        try:
            record_page(request, "convert_dl", f"{fmt}:{r if r in CONVERT_RANGES else '-'}", db)
        except Exception:
            pass
    return Response(status_code=204)


# 타닥타닥 구독 배너(그림 한 장, 누르면 tdtd.io) 클릭 — 2026-10-07 사용자님 "클릭 수를 체크해보자".
# 메인은 쓰는 자리 바 아래(app/routers/design.py), 전체 무료폰트 보기는 목록 위(static/fonts.html).
# 세는 규칙은 위와 같다(봇 제외, 같은 사람이 30분 안에 다시 누르면 한 번). 어드민 통계가 이 순서·이름으로 보여 준다.
TDTD_AD_SPOTS = {
    "home": "메인 (쓰는 자리 아래)",
    "fonts": "전체 무료폰트 보기 (목록 위)",
}


@router.post("/api/track/tdtd-ad", include_in_schema=False)
def track_tdtd_ad(request: Request, spot: str = "", db: Session = Depends(get_db)):
    if spot in TDTD_AD_SPOTS:
        try:
            record_page(request, "tdtd_ad", spot, db)
        except Exception:
            pass
    return Response(status_code=204)
