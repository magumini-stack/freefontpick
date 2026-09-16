# 폰트픽 운영 이미지
#
# 시각(TZ)은 일부러 건드리지 않는다 — 컨테이너를 UTC 로 둔다.
# created_at 은 SQLite 의 CURRENT_TIMESTAMP(=UTC)로 쌓여 왔고 카페24
# 컨테이너도 UTC 였다. 여기서 Asia/Seoul 로 바꾸면 그날부터 쌓이는
# 시각만 9시간 어긋나 과거 데이터와 섞인다.
#
# requirements.txt 의 패키지는 cp311 manylinux 휠이 모두 있어
# 빌드 도구(gcc 등)를 깔 필요가 없다. 이미지가 그만큼 작고 빠르다.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8

# 루트로 돌리지 않는다. UID 1000 은 우분투 첫 사용자와 같아서
# 호스트에서 마운트한 user_data 의 소유권이 그대로 맞는다.
RUN useradd -m -u 1000 app

WORKDIR /app

# 의존성을 먼저 깐다. 코드만 바뀐 배포에서는 이 층이 캐시에 남아
# 빌드가 몇 초로 끝난다.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

# 앱이 쓰는 자리(DB·업로드 폰트·생성 캐시). 호스트 디렉터리를 여기에
# 마운트하므로 컨테이너를 지우고 다시 만들어도 자료는 남는다.
# 이미지에도 빈 폴더를 둔다 — 마운트를 빠뜨려도 앱이 뜨긴 한다.
RUN mkdir -p /app/user_data && chown app:app /app/user_data

USER app

EXPOSE 8000

# 앞단(nginx)이 살아 있어도 앱이 죽으면 502 가 난다. 도커가 먼저 알도록
# 가장 가벼운 엔드포인트를 두드린다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/robots.txt',timeout=4).status==200 else 1)"

# Procfile 과 같은 옵션. limit-concurrency 는 ZIP 스트리밍이 몰릴 때
# 메모리를 막는 울타리다 (ZIP 한 개가 최대 50MB).
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--http", "h11", \
     "--timeout-keep-alive", "30", \
     "--limit-concurrency", "50"]
