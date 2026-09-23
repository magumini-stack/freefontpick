# 폰트 찾기 엔진(finder) 이미지 — 앱(freefontpick)과 따로 돈다.
#
# 왜 따로인가: OCR(onnxruntime)·opencv·scipy 가 앱 이미지보다 훨씬 무겁고, 메모리도 따로 울타리를
# 쳐야 한다(서버 2GB — 앱 1GB, finder 700MB). 앱은 /api/find/* 를 이 컨테이너로 넘기기만 한다.
#
# OCR 모델(PP-OCRv5 mobile det/rec/cls, 19MB)은 이미지에 넣지 않고 데이터 볼륨 /data/models 에서 읽는다
# (finder.py 의 FINDER_MODELS). 빌드 때 rapidocr 로 내려받게 했더니 서버에서 modelscope.cn 단계가
# 실패했다(2026-09-23) — 빌드도 실행도 인터넷을 안 타게 바꿨다. 파일은 finder_data.tar.gz 로 같이 올린다.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8 \
    OMP_NUM_THREADS=2

RUN useradd -m -u 1000 app
WORKDIR /app

# slim 이미지에는 opencv-python-headless(libgthread)·onnxruntime(libgomp)이 찾는 공유 라이브러리가 없다
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

# /data/models 가 비어 있으면 rapidocr 가 처음 쓸 때 여기로 내려받으려 한다 — app 사용자가 쓸 수 있게만 해 둔다
RUN chown -R app:app /usr/local/lib/python3.11/site-packages/rapidocr/models

# 폰트 목록·폰트 파일·글자 묶음 캐시가 놓이는 자리(호스트 폴더를 마운트한다)
RUN mkdir -p /data && chown app:app /data
USER app
EXPOSE 8010
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1"]
