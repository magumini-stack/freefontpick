"""디자인 리뉴얼 D (애플 디자인 · 로고 남색) 스위치 — 2026-10-30

켜면 사이트의 모든 HTML 응답 </head> 앞에 static/renew.css 를, </body> 앞에
static/renew.js 를 끼운다. 페이지 HTML·헤더는 그대로 두고 겉(CSS)만 덧씌우는
방식이라, 끄면 바로 지금 화면으로 돌아간다.

    켜기:  아래 ON 을 True 로 바꿔 배포 (또는 서버 .env 에 FFP_RENEW=1)
    끄기:  ON = False 로 되돌려 배포 (또는 FFP_RENEW=0)

renew.css·renew.js 의 정본은 projects\\폰트픽\\리뉴얼_시안\\themes\\d.css·d.js 다.
시안 폴더에서 고친 뒤 그 폴더의 publish.py 로 static/ 에 옮긴다 — static 쪽을 직접 고치지 말 것.

주소는 /static/… 로 적어 두면 main.py 의 _stamp_assets 가 내용 해시 판(/s/<md5>/…)으로
바꿔 준다. 그래서 CSS 를 고쳐 배포하면 CDN 에 남은 옛 파일 걱정 없이 새로 받는다.
"""
import os

ON = True    # 2026-10-30 사용자님 지시로 켬

# 관리자 화면은 일 보는 곳이라 바꾸지 않는다.
SKIP_PREFIXES = ("/admin",)

_HEAD = ('<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/'
         'pretendardvariable-dynamic-subset.min.css">\n'
         '<link rel="stylesheet" href="/static/renew.css">\n')
_BODY = '<script src="/static/renew.js" defer></script>\n'


def enabled() -> bool:
    v = os.getenv("FFP_RENEW")
    return ON if v is None else v == "1"


def inject(html: str, path: str) -> str:
    """renew.css·renew.js 를 끼운다. 꺼져 있거나 관리자 화면이면 그대로 돌려준다."""
    if not enabled() or path.startswith(SKIP_PREFIXES) or "</head>" not in html:
        return html
    html = html.replace("</head>", _HEAD + "</head>", 1)
    i = html.rfind("</body>")
    if i != -1:
        html = html[:i] + _BODY + html[i:]
    return html
