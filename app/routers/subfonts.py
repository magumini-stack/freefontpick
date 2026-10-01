"""구독 폰트 미리 써보기용 웹폰트(한글 2,350자 판) — 2026-10-01 사용자님 결정(2안).

  GET /api/subfonts/file/{h}.woff2

전체 폰트 보기의 '미리 써보기'에 문구를 치면 구독 카드도 그 문구로 그린다.
/static/subfonts/ 에 있는 것은 견본 문구 글자만 담은 판이라 다른 글자가 없다.
그래서 글을 쳤을 때만, 화면에 보이는 카드만 이 주소로 2,350자 판을 받는다.

어디서 오나
-----------
tdtd.io 의 /fontfile.php?f=<h>&s=full 이 원본이다(tdtd-webfont 가 구운 것, 평균 200KB).
408종을 git 에 넣으면 92MB 라 저장소와 도커 이미지가 같이 불어난다. 그래서 처음
불렸을 때 서버가 tdtd.io 에서 받아 /app/user_data/subfonts_full 에 두고, 다음부터는
그것을 준다. fontfile.php 는 Referer 가 없는 요청을 통과시킨다.

지키는 것 (tdtd.io fontfile.php 와 같은 수준)
-----------------------------------------
  - Referer 가 있으면 폰트픽 주소여야 한다. 주소창에 직접 친 요청(Sec-Fetch-Dest: document)은 막는다.
  - IP 마다 10분에 150개. 넘으면 오류 대신 견본 문구 판을 준다(화면은 안 깨지고 긁는 쪽은 쓸모없는 파일).
  - 캐시는 private — 앞단(CDN)이 담아 두면 위 검사를 건너뛰고 누구에게나 나간다.
  - tdtd.io 가 제한에 걸려 견본 판을 돌려주면(크기가 같다) 담아 두지 않는다.
완전한 방어는 아니다. 개발자도구로 한 폰트를 받아가는 개인은 못 막는다 — tdtd.io 도 같다.
"""
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from ..site import SITE_URL

router = APIRouter(tags=["subfonts"])

ROOT = Path(__file__).resolve().parent.parent.parent
LIGHT_DIR = ROOT / "static" / "subfonts"
FULL_DIR = Path(os.getenv("SUBFONT_FULL_DIR", "/app/user_data/subfonts_full"))
SOURCE = "https://tdtd.io/fontfile.php?f={h}&s=full"
_UA = "Mozilla/5.0 (compatible; FreeFontPick/1.0; +https://freefontpick.tdtd.io)"
_MAX = 3 * 1024 * 1024

_H = re.compile(r"^[0-9a-f]{10}$")
_ALLOWED_HOSTS = {urlsplit(SITE_URL).hostname, "freefontpick.tdtd.io", "freefontpick.co.kr",
                  "www.freefontpick.co.kr", "localhost", "127.0.0.1"}

WINDOW, LIMIT = 600, 150
_hits: dict = {}
_hits_lock = threading.Lock()
_fetch_lock = threading.Lock()
_known: set = set()
_known_mtime = 0.0

FULL_HEADERS = {"Cache-Control": "private, max-age=2592000", "X-Content-Type-Options": "nosniff"}
LIGHT_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _known_hashes() -> set:
    """fonts.json 에 있는 표식만 받는다 — 아무 표식이나 tdtd.io 로 넘기지 않게."""
    global _known, _known_mtime
    p = LIGHT_DIR / "fonts.json"
    try:
        m = p.stat().st_mtime
        if m != _known_mtime:
            _known = {f["h"] for f in json.loads(p.read_text(encoding="utf-8"))["fonts"]}
            _known_mtime = m
    except Exception:
        pass
    return _known


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "0")


def _allow(ip: str) -> bool:
    now = time.time()
    with _hits_lock:
        start, count = _hits.get(ip, (now, 0))
        if now - start >= WINDOW:
            start, count = now, 0
        count += 1
        _hits[ip] = (start, count)
        if len(_hits) > 5000:   # 오래된 칸 청소
            for k in [k for k, (s, _) in _hits.items() if now - s >= WINDOW]:
                _hits.pop(k, None)
    return count <= LIMIT


def _light(h: str) -> Response:
    return FileResponse(LIGHT_DIR / f"{h}.woff2", media_type="font/woff2", headers=LIGHT_HEADERS)


def _fetch(h: str) -> bool:
    """tdtd.io 에서 2,350자 판을 받아 FULL_DIR 에 둔다. 제대로 된 full 이 아니면 False."""
    dst = FULL_DIR / f"{h}.woff2"
    with _fetch_lock:
        if dst.is_file():
            return True
        req = urllib.request.Request(SOURCE.format(h=h), headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read(_MAX + 1)
        except Exception:
            return False
        light = LIGHT_DIR / f"{h}.woff2"
        if (len(data) > _MAX or not data.startswith(b"wOF2")
                or (light.is_file() and len(data) <= light.stat().st_size)):
            return False   # 제한에 걸려 견본 판이 왔거나 깨진 응답
        FULL_DIR.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, dst)
        return True


@router.get("/api/subfonts/file/{name}")
def subfont_full(name: str, request: Request):
    h = name[:-6] if name.endswith(".woff2") else ""
    if not _H.match(h) or h not in _known_hashes():
        raise HTTPException(status_code=404)
    ref = request.headers.get("referer")
    if ref and (urlsplit(ref).hostname or "").lower() not in _ALLOWED_HOSTS:
        raise HTTPException(status_code=403)
    if request.headers.get("sec-fetch-dest") == "document":
        raise HTTPException(status_code=403)
    if not _allow(_client_ip(request)):
        return _light(h)
    path = FULL_DIR / f"{h}.woff2"
    if path.is_file() or _fetch(h):
        return FileResponse(path, media_type="font/woff2", headers=FULL_HEADERS)
    return _light(h)
