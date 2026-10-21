"""텍스트 디자인 — /text-design (2026-10-21).

사용자님 10/19 "이미지 만들기 모달을 업그레이드해서 제대로 서비스" → 10/21 "원래 모달은 그대로 두고 새 페이지로,
터치 몇 번으로 바로 결과물이 나오게, 용도별 추천 효과만" → 시안 여러 판(Desktop\\projects\\폰트픽\\글자이미지_시안)
→ "오늘 작업한 거 다 올려야 해".

쓸 곳 5가지(유튜브 썸네일·영상 자막·감성 문구·스티커·굿즈·상세페이지·이벤트) × 추천 꾸밈 7개 + 더 꾸미기.
그리기는 전부 방문자 브라우저의 캔버스에서 한다. 폰트 목록·쓸 곳 자료는 시안 폴더의 build.py 가 페이지에 실어 두고
publish.py 가 static/text-design.html 로 갈아 끼운다(이 저장소에서 직접 고치면 다음 publish 때 덮인다).
이 라우트는 머리글·바닥글만 끼워 돌려준다 — 자판기(/font-vending)와 같은 방식.

?embed : 폰트 상세페이지의 '이 폰트로 디자인하기' 모달(iframe) 안에서 쓴다. 머리글·바닥글·광고·측정 태그 없이,
         검색에는 안 잡히게(noindex) 돌려준다. ?font=ID 는 페이지 스크립트가 읽어 글씨를 그 폰트로 고정한다.

입구: 머리글 '폰트 도구' 묶음, 메인 기능 입구 6칸(클릭은 track.py 'tdesign'), 상세페이지 제목 줄 단추, 사이트맵(seo.py).
광고: 저장 단추 아래 칸 — app/header.py AD_SLOTS['text_design'].
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..header import inject_header

router = APIRouter(tags=["text_design"])

TEMPLATE = Path(__file__).resolve().parent.parent.parent / "static" / "text-design.html"

_AD_BOX = '    <div class="ffp-ad ad" data-ad-key="text_design" data-ad-format="auto"><span class="ffp-ad-lbl">광고</span></div>\n'


@router.get("/text-design", response_class=HTMLResponse)
def text_design_page(request: Request, db: Session = Depends(get_db)):
    html = TEMPLATE.read_text(encoding="utf-8")
    if "embed" in request.query_params:
        # 모달 안 — 머리글 자리가 없으면 inject_header 가 측정·광고 태그도 넣지 않는다.
        # 상세페이지 조회가 이미 잡혔으므로 열람 기록도 남기지 않는다.
        html = (html.replace("<!--FFP_HEADER-->", "").replace("<!--FFP_FOOTER-->", "")
                    .replace(_AD_BOX, "")
                    .replace('<meta name="robots" content="index, follow, max-image-preview:large">',
                             '<meta name="robots" content="noindex, nofollow">'))
        return HTMLResponse(inject_header(html, "tdesign"))
    try:
        from ..font_views import record_page
        record_page(request, "text_design", "", db)   # 텍스트 디자인 열람 (page_views 에 쌓인다)
    except Exception:
        pass
    return HTMLResponse(inject_header(html, "tdesign"))
