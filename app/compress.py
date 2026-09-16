"""응답 압축 — 텍스트 계열만 gzip 으로 보낸다.

앞단이 압축해 줄 거라고 기대하지 않는다. 카페24는 엣지에서 해 줬지만
에그호스팅 엣지는 text/html 만 압축한다(2026-09-16 실측 — gzip_types 미설정).
그 차이로 /api/fonts 가 35KB → 226KB 가 되어 갤러리가 2초 넘게 비었다.
앱이 직접 압축하면 앞단이 무엇이든 같은 결과가 나온다. nginx 는 이미
Content-Encoding 이 붙은 응답을 다시 압축하지 않으므로 겹쳐도 안전하다.

Starlette 의 GZipMiddleware 를 그대로 걸지 않는 이유 — 타입을 가리지 않는다.
ZIP(최대 50MB)·woff2·PNG 는 이미 압축된 바이트라 다시 눌러도 줄지 않고
CPU 만 태운다. 1코어 서버에서 다운로드가 몰리면 그대로 병목이 된다.
스트리밍 응답은 Content-Length 까지 사라져 다운로드 진행률도 안 보인다.

응답 타입은 응답이 시작돼야 알 수 있으므로 **요청 경로로 미리 가른다.**
잘못 갈라도 깨지지는 않는다 — 브라우저는 Content-Encoding 을 보고 풀기만
한다. 손해는 CPU 뿐이라, 무거운 것(다운로드·폰트·이미지)만 확실히 뺀다.
"""
from starlette.middleware.gzip import GZipMiddleware

# 이미 압축돼 있어 다시 눌러도 줄지 않는 것들
_NO_GZIP_SUFFIXES = (
    ".woff2", ".woff", ".ttf", ".otf",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".ico",
    ".zip", ".gz", ".br", ".mp4", ".webm", ".pdf",
    # 확장자 없이 바이너리를 내보내는 API
    #   /api/fonts/{id}/file            woff2
    #   /api/fonts/{id}/download        ZIP
    #   /api/wisefont/{slug}/download   ZIP
    #   /api/fonts/{id}/sample-image    이미지
    #   /api/submissions/{id}/image     이미지
    "/file", "/download", "/sample-image", "/image",
)
_NO_GZIP_PARTS = (
    "/file/",       # /api/fonts/{id}/file/{name}      woff2
    "/webfont/",    # /api/fonts/{id}/webfont/{name}   woff2  (webfont.css 는 해당 없음)
    "/piece/",      # /api/fonts/{id}/piece/...         PNG
)


def gzip_worthy(path: str) -> bool:
    """이 경로의 응답을 압축할 가치가 있는가."""
    p = path.lower()
    if p.endswith(_NO_GZIP_SUFFIXES):
        return False
    return not any(part in p for part in _NO_GZIP_PARTS)


class SelectiveGZipMiddleware:
    """텍스트 계열 응답만 gzip 으로 보낸다. 판단 근거는 모듈 설명 참고."""

    def __init__(self, app, minimum_size: int = 1024, compresslevel: int = 6):
        self.app = app
        # 1코어라 최고 압축(9)은 과하다. 6 이 크기와 CPU 의 균형점이다.
        #
        # minimum_size 는 이 앱에서 **사실상 듣지 않는다.** Starlette 는 본문이
        # 한 조각으로 올 때만 크기를 보고, 스트리밍이면 크기와 상관없이 누른다.
        # 그런데 main.py 의 @app.middleware("http") 층을 지나면 모든 응답이
        # 스트리밍으로 바뀐다(2026-09-16 확인). 그래서 수십 바이트짜리 응답도
        # 압축돼 20바이트쯤 커진다. 내용은 멀쩡하고 손해가 미미해 그대로 둔다.
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size,
                                   compresslevel=compresslevel)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and gzip_worthy(scope.get("path", "")):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)
