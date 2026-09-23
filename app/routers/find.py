"""이미지로 폰트 찾기 — 앱은 요청을 finder 서비스(FINDER_URL)로 넘기기만 한다.

finder 는 OCR·비교 엔진이 든 별도 컨테이너(finder/service.py). 브라우저는 이 앱의 /api/find/* 만 본다.
FINDER_URL 이 없으면(로컬에서 finder 를 안 띄운 경우) 503 을 준다 — 페이지는 "지금은 자동 찾기를 쓸 수 없어요"로 보여 준다.
"""
import os

import httpx
from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response

router = APIRouter(prefix="/api/find", tags=["find"])
FINDER_URL = os.getenv("FINDER_URL", "").rstrip("/")
# 앞단 nginx(에그호스팅 관리)가 60초에 504 를 주므로 그보다 먼저 우리가 답한다 — 화면은 504 를 받으면 몇 초 뒤 다시 묻는다.
# finder 는 처음 보는 글자의 묶음을 만드는 동안(1,327벌, 글자당 15~25초) 잠겨 있어서 그 사이 요청은 기다리다 여기 걸린다.
TIMEOUT = httpx.Timeout(55.0, connect=5.0)


def _off():
    return JSONResponse({"detail": "지금은 자동 찾기를 쓸 수 없습니다"}, status_code=503)


def _busy():
    return JSONResponse({"detail": "서버가 글자를 준비하는 중이라 시간이 걸려요. 잠시 후 다시 해 주세요."}, status_code=504)


@router.get("/health")
async def health():
    if not FINDER_URL:
        return _off()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(FINDER_URL + "/find/health")
        return JSONResponse(r.json(), status_code=r.status_code)
    except httpx.TimeoutException:
        return _busy()
    except Exception:
        return _off()


@router.post("/detect")
async def detect(request: Request, image: UploadFile = File(...)):
    if not FINDER_URL:
        return _off()
    raw = await image.read()
    if len(raw) > 8 * 1024 * 1024:
        return JSONResponse({"detail": "이미지는 8MB 까지만 받습니다"}, status_code=413)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(FINDER_URL + "/find/detect", files={"image": (image.filename or "image", raw, image.content_type or "application/octet-stream")})
        return Response(r.content, status_code=r.status_code, media_type="application/json")
    except httpx.TimeoutException:
        return _busy()
    except Exception:
        return _off()


@router.post("/match")
async def match(request: Request):
    if not FINDER_URL:
        return _off()
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(FINDER_URL + "/find/match", content=body, headers={"content-type": "application/json"})
        return Response(r.content, status_code=r.status_code, media_type="application/json")
    except httpx.TimeoutException:
        return _busy()
    except Exception:
        return _off()


@router.get("/render")
async def render(fid: str, w: int, text: str, h: int = 56):
    if not FINDER_URL:
        return _off()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(FINDER_URL + "/find/render", params={"fid": fid, "w": w, "text": text[:40], "h": h})
        return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "image/png"),
                        headers={"Cache-Control": "public, max-age=86400"})
    except httpx.TimeoutException:
        return _busy()
    except Exception:
        return _off()
