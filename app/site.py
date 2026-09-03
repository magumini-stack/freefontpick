"""사이트 주소를 두는 단 한 곳.

왜 필요한가
----------
도메인 문자열이 소스 22개 파일 69곳에 흩어져 있었다. 상수만 해도
BASE_URL 이 design.py · magazine.py · use_case_route.py · wisefont.py
네 곳에 따로 정의돼 있었고, seo.py 만 환경변수를 읽고 있었다.

도메인을 옮길 때 이 상태면 전수 검색을 해야 하고, 한 군데만 빠뜨려도
canonical 이 옛 도메인을 가리킨 채로 나간다. 그러면 새 주소는 열리는데
canonical 은 옛 주소를 가리키고, 옛 주소는 301 로 새 주소를 가리켜서
신호가 정면으로 충돌한다. 구글이 둘 다 색인에서 빼는 가장 흔한 사고다.

그래서 여기 하나만 둔다. 도메인을 옮길 때는 **환경변수 SITE_URL 만**
바꾸면 되고 코드는 손대지 않는다.

정적 HTML 은?
------------
static/*.html 은 파이썬이 아니라 환경변수를 못 읽는다. 그래서 그쪽은
{{FFP_ORIGIN}} 마커를 박아 두고 app/header.py 의 inject_header 가
채운다. 페이지를 내보내는 라우터 열네 곳이 전부 그 함수를 지나므로
한 곳만 채우면 전부 채워진다.
"""
import os

# 예: SITE_URL=https://freefontpick.tdtd.io
# 끝의 / 는 떼어 둔다 — 붙이는 쪽에서 늘 "/경로" 형태로 이어 쓴다.
SITE_URL = os.getenv("SITE_URL", "https://freefontpick.tdtd.io").rstrip("/")

# 정적 HTML 이 쓰는 마커. 값이 아니라 이름을 한 곳에 둔다 —
# 마커 문자열을 여기저기 적으면 오타가 나도 조용히 안 채워진다.
ORIGIN_MARKER = "{{FFP_ORIGIN}}"
