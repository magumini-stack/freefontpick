# 폰트 찾기 엔진(finder) 이미지 — 앱(freefontpick)과 따로 돈다.
#
# 왜 따로인가: OCR(onnxruntime)·opencv·scipy 가 앱 이미지보다 훨씬 무겁고, 메모리도 따로 울타리를
# 쳐야 한다(서버 2GB — 앱 1GB, finder 700MB). 앱은 /api/find/* 를 이 컨테이너로 넘기기만 한다.
#
# OCR 모델(PP-OCRv5 mobile det/rec, ~20MB)은 빌드 때 받아 이미지에 넣는다 — 운영 중에 인터넷을
# 안 타고, 컨테이너를 새로 만들어도 다시 받지 않는다.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8 \
    OMP_NUM_THREADS=2

RUN useradd -m -u 1000 app
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

# OCR 모델을 미리 받아 둔다(rapidocr 는 처음 쓸 때 내려받는다).
RUN python -c "from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType; RapidOCR(params={'Det.ocr_version': OCRVersion.PPOCRV5, 'Det.model_type': ModelType.MOBILE, 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE, 'Rec.lang_type': LangRec.KOREAN})" \
    && chown -R app:app /usr/local/lib/python3.11/site-packages/rapidocr/models

# 폰트 목록·폰트 파일·글자 묶음 캐시가 놓이는 자리(호스트 폴더를 마운트한다)
RUN mkdir -p /data && chown app:app /data
USER app
EXPOSE 8010
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1"]
