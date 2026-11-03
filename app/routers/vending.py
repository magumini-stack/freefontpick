"""추천 폰트 자판기 — /font-vending (2026-10-16).

사용자님 10/15: "질문 3개, 결과값은 엔진 안에서 매번 달라지게, 다시 뽑기도, 새 페이지로" → 시안 여러 판
(Desktop\\projects\\폰트픽\\맞춤폰트자판기) → 10/16 "이제 올리자". 옛 이름은 '맞춤 폰트 자판기'.

뽑기는 전부 방문자의 브라우저에서 한다. 후보·점수는 시안 폴더의 engine.py → export_pools.py 가 미리 만든
static/vending/data.json(쓰임×느낌 48개 통, 폰트마다 인기 순위)을 페이지가 받아 쓰고, 이 라우트는 템플릿
(static/font-vending.html)에 머리글·바닥글만 끼워 돌려준다 — 폰트 변환(/font-convert)과 같은 방식.
템플릿과 데이터는 시안 폴더의 publish.py 가 갈아 끼운다(이 저장소에서 직접 고치면 다음 publish 때 덮인다).

입구: 메인 제목 아래 [추천 폰트 자판기] 단추(클릭은 track.py 'vending'), 사이트맵(seo.py).
광고: 결과 '오늘의 추천 폰트' 위 가로형 칸 — app/header.py AD_SLOTS['vending_result'].

사진으로 뽑기 (2026-11-03 사용자님: "질문 말고 내 이미지 올려서 추천받기, 이미지는 클로드 api 로"):
POST /api/vending/photo 가 사진을 Claude 에게 보여 주고 질문 1·2번 답(쓰임·느낌)과 사진에 어울리는 짧은 문구만
받는다. 폰트를 고르는 건 지금처럼 화면의 엔진 — Claude 가 폰트 이름을 지어내지 않고, 질문형과 결과가 같은 규칙을 탄다.
켜는 법: 서버 .env 에 ANTHROPIC_API_KEY. 없으면 화면에 사진 칸이 안 나온다(/*PHOTO*/ 자리).
비용 울타리: 사진은 긴 변 1024px JPEG 로 줄여 보내고(화면에서도 줄인다), IP 당 하루 VENDING_PHOTO_PER_IP(기본 15)번,
서버 전체 하루 VENDING_PHOTO_DAILY(기본 1500)번. 사진은 저장하지 않는다(메모리에서 줄여 보내고 버림, EXIF 도 떨어짐).
"""
import base64
import io
import json
import logging
import os
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..database import get_db
from ..header import inject_header

router = APIRouter(tags=["vending"])

TEMPLATE = Path(__file__).resolve().parent.parent.parent / "static" / "font-vending.html"


@router.get("/font-vending", response_class=HTMLResponse)
def font_vending_page(request: Request, db: Session = Depends(get_db)):
    try:
        from ..font_views import record_page
        record_page(request, "vending", "", db)      # 자판기 열람 (어드민 통계 요약엔 아직 칸이 없다 — page_views 에 쌓인다)
    except Exception:
        pass
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("/*PHOTO*/", "window.VENDING_PHOTO=true;" if _api_key() else "")
    return HTMLResponse(inject_header(html, "vending"))


# ── 사진으로 뽑기 ─────────────────────────────────────────────────────
log = logging.getLogger("vending.photo")

# 화면(vending_template.html)의 USES·MOODS 와 같은 값이어야 한다 — 이 값이 그대로 질문 1·2번 단추를 누른다
USES = ["썸네일", "자막", "인스타", "블로그", "PPT", "포스터", "로고", "굿즈"]
MOODS = ["깔끔한", "귀여운", "감성적인", "강렬한", "고급스러운", "레트로"]
MAX_UPLOAD = 8 * 1024 * 1024
SIDE = 1024

SYSTEM = """너는 무료폰트 사이트 '폰트픽'의 추천 폰트 자판기다. 방문자가 올린 사진 한 장을 보고, 그 사진과 함께 쓸 글씨를 고르는 데 필요한 답 두 개와 짧은 문구를 정한다.

use — 이 사진(또는 이 사진 같은 콘텐츠)에 글씨를 얹는다면 어디에 쓸지 하나:
- 썸네일: 유튜브 썸네일이나 그 캡처, 큰 제목을 얹을 영상 장면
- 자막: 영상의 한 장면(브이로그·인터뷰·여행 영상 화면)
- 인스타: 일상·음식·카페·풍경·인물 사진처럼 피드에 올릴 사진. 애매하면 이것
- 블로그: 글이 많은 화면, 정보 정리, 후기용 사진
- PPT: 발표 화면, 표·그래프, 회사·업무 장면
- 포스터: 전단·행사·할인 안내, 공연·전시 포스터
- 로고: 가게 간판·매장 앞, 상품 포장, 브랜드 로고
- 굿즈: 캐릭터·일러스트·스티커·귀여운 소품

mood — 보는 사람이 어떤 반응이면 좋을지, 사진의 색·빛·구도·소재를 보고 하나:
- 깔끔한: 정돈되고 여백이 많고 단정하다, 밝고 미니멀
- 귀여운: 아기자기, 동물·캐릭터·파스텔, 동글동글
- 감성적인: 따뜻하고 잔잔하다, 햇살·노을·카페·일기 같은 분위기
- 강렬한: 대비가 세고 역동적이다, 원색·스포츠·할인·놀람
- 고급스러운: 차분하고 품위 있다, 어두운 톤·금색·여백 많은 고급 매장·호텔·와인
- 레트로: 옛날 느낌, 바랜 색·필름·간판·복고 소품

reading — 사진에서 읽은 느낌을 친근한 한국어 한 구절로, 20자 안팎(예: "햇살 드는 잔잔한 카페 창가"). 사람이 있어도 누구인지 짐작하거나 외모를 평가하지 않는다.
phrase — 이 사진 위에 얹으면 어울릴 한국어 문구 하나, 14자 안쪽, 줄바꿈·이모지·따옴표 없이. 사진 속 소재·계절·장면에서 나온 구체적인 말로 쓰고, 어느 사진에나 붙는 흔한 말(오늘도·천천히·화이팅 같은)은 피한다. 사진 속 글자를 그대로 베끼지 말고, 이름·연락처 같은 개인 정보는 넣지 않는다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "use": {"type": "string", "enum": USES},
        "mood": {"type": "string", "enum": MOODS},
        "reading": {"type": "string"},
        "phrase": {"type": "string"},
    },
    "required": ["use", "mood", "reading", "phrase"],
    "additionalProperties": False,
}

_client = None
_count = {"day": None, "all": 0, "ip": {}}


def _api_key() -> str:
    return (os.getenv("ANTHROPIC_API_KEY") or "").strip()


def _anthropic():
    global _client
    if _client is None:
        import anthropic   # 키가 없는 서버에선 부르지 않는다
        # 응답은 gzip 으로 받는다 — SDK(httpx2)의 brotli 풀기는 Brotli 1.2 를 바라는데, 이 사이트는 폰트 굽기 때문에
        # requirements 에서 brotli==1.1.0 으로 묶여 있어 br 응답을 못 풀고 'Connection error' 가 난다(11/3 실측)
        _client = anthropic.AsyncAnthropic(api_key=_api_key(), timeout=40.0, max_retries=1,
                                           default_headers={"Accept-Encoding": "gzip, deflate"})
    return _client


def _limit_hit(ip: str) -> str:
    """오늘 횟수를 넘었으면 이유, 아니면 '' — 한 프로세스(uvicorn 1개)라 메모리로 센다. 재시작하면 0 부터."""
    today = date.today()
    if _count["day"] != today:
        _count.update(day=today, all=0, ip={})
    if _count["all"] >= int(os.getenv("VENDING_PHOTO_DAILY", "1500")):
        return "all"
    if _count["ip"].get(ip, 0) >= int(os.getenv("VENDING_PHOTO_PER_IP", "15")):
        return "ip"
    return ""


def _shrink(raw: bytes) -> bytes:
    """긴 변 1024px JPEG 로. 회전 정보는 반영하고 EXIF(촬영 위치 등)는 버린다."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(raw))
    if im.width * im.height > 60_000_000:
        raise ValueError("too big")
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((SIDE, SIDE))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85)
    return out.getvalue()


def _fail(status: int, code: str, msg: str):
    return JSONResponse({"error": code, "message": msg}, status_code=status)


@router.post("/api/vending/photo")
async def vending_photo(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    from .likes import _client_ip
    if not _api_key():
        return _fail(503, "off", "지금은 사진 추천을 쉬고 있어요. 질문으로 뽑아 주세요.")
    ip = _client_ip(request)
    hit = _limit_hit(ip)
    if hit:
        return _fail(429, "limit", "오늘 사진 추천을 많이 써서 잠시 쉬어요. 질문으로 뽑아 주세요." if hit == "all"
                     else "오늘은 사진 추천을 다 썼어요. 내일 다시 해 주세요. 질문으로는 계속 뽑을 수 있어요.")
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        return _fail(413, "big", "사진이 너무 커요. 8MB 아래로 올려 주세요.")
    try:
        jpg = await run_in_threadpool(_shrink, raw)   # 큰 사진 풀기는 몇백 ms — 다른 요청을 막지 않게
    except Exception:
        return _fail(400, "bad", "이 사진은 읽을 수 없어요. JPG·PNG 사진으로 올려 주세요.")
    _count["all"] += 1
    _count["ip"][ip] = _count["ip"].get(ip, 0) + 1

    import anthropic
    model = os.getenv("VENDING_PHOTO_MODEL", "claude-haiku-5-5")
    try:
        msg = await _anthropic().messages.create(
            model=model,
            max_tokens=2000,
            system=SYSTEM,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.standard_b64encode(jpg).decode("ascii")}},
                {"type": "text", "text": "이 사진에 어울리는 폰트를 뽑게 답을 정해 줘."},
            ]}],
        )
    except anthropic.RateLimitError:
        return _fail(429, "busy", "사진을 읽는 곳이 붐벼요. 잠시 뒤 다시 해 주세요.")
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        log.warning("vending photo api error: %r", e)
        return _fail(502, "api", "사진을 읽지 못했어요. 잠시 뒤 다시 해 주세요.")
    u = msg.usage
    log.info("vending photo %s in=%s out=%s stop=%s", model, u.input_tokens, u.output_tokens, msg.stop_reason)
    if msg.stop_reason == "refusal":
        return _fail(422, "refusal", "이 사진으로는 추천하기 어려워요. 다른 사진이나 질문으로 뽑아 주세요.")
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        ans = json.loads(text)
    except ValueError:
        return _fail(502, "api", "사진을 읽지 못했어요. 잠시 뒤 다시 해 주세요.")
    use = ans.get("use") if ans.get("use") in USES else "인스타"
    mood = ans.get("mood") if ans.get("mood") in MOODS else "감성적인"
    clean = lambda t, n: " ".join(str(t or "").replace("|", " ").split())[:n]
    try:
        from ..font_views import record_page
        record_page(request, "vending_photo", "", db)   # 사진으로 뽑은 횟수 (page_views)
    except Exception:
        pass
    return {"use": use, "mood": mood, "reading": clean(ans.get("reading"), 30), "phrase": clean(ans.get("phrase"), 16)}
