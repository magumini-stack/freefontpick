"""클릭 기록 — 메인 4칸 메뉴 (2026-10-04).

  POST /api/track/home-tool?tool=pair|find|gif|apps     (공개, 204)

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
HOME_TOOLS = {
    "pair": "폰트 조합 찾기",
    "find": "이미지로 폰트 찾기",
    "gif": "GIF 만들기",
    "apps": "글자로 노는 앱",
}


@router.post("/api/track/home-tool", include_in_schema=False)
def track_home_tool(request: Request, tool: str = "", db: Session = Depends(get_db)):
    if tool in HOME_TOOLS:
        try:
            record_page(request, "home_tool", tool, db)
        except Exception:
            pass
    return Response(status_code=204)
