"""폰트 찾기 엔진 서비스 — 이미지 → 글자 줄 → 비슷한 폰트.

앱(freefontpick)과 따로 도는 작은 FastAPI. 앱이 /api/find/* 로 받은 요청을 여기(FINDER_URL)로 넘긴다.
브라우저가 이 서비스에 직접 닿지는 않는다(컨테이너 안 주소).

    POST /find/detect   multipart image → {image_id, width, height, lines:[{i, quad, text, conf}]}
    POST /find/match    {image_id, line, text?} → {text, results:[{fid, w, name, maker, source, link, why}], verdict}
    GET  /find/render   ?fid=&w=&text=   → 그 폰트로 글자를 그린 PNG (타닥타닥 유료 폰트 파일은 안 나간다)
    GET  /find/health

실험실(Desktop\\projects\\fontfinder-lab)의 engine_v0.py·typo.py·finder.py 를 그대로 옮겨 쓴다.
폰트 목록(/data/catalog.json)·폰트 파일(/data/fonts)·글자 묶음 캐시(/data/stacks)는 build_catalog.py 가 만든다.
메모리: 서버가 2GB 라 폰트는 지연 로드, 글자 묶음은 FINDER_MAX_STACKS(기본 30)개만 들고 있는다(≈ 400~500MB).
"""
import io
import os
import secrets
import threading
import time

import numpy as np
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel

import engine_v0 as E
import finder as F

DATA = os.environ.get("FINDER_DATA", "/data")
CATALOG = os.environ.get("FINDER_CATALOG", os.path.join(DATA, "catalog.json"))   # 로컬 시험은 실험실 목록을 가리킬 수 있다
os.environ.setdefault("FINDER_MODELS", os.path.join(DATA, "models"))              # OCR 모델 파일 3개(finder.py) — 데이터와 같이 올린다
MAX_UPLOAD = 8 * 1024 * 1024        # 8MB
MAX_SIDE = 1600                     # 이보다 크면 줄여서 본다(OCR 은 어차피 줄여 본다)
IMAGE_TTL = 15 * 60                 # 올린 이미지는 15분만 들고 있는다(줄을 고르는 동안)
MAX_IMAGES = 40
RENDER_CACHE = 300
TDTD_ABOUT = "https://tdtd.io/fonts/about"   # 타닥타닥 폰트정보(폰트보기) 페이지 — #f=<해시> 로 폰트 하나를 짚는다

app = FastAPI(title="freefontpick finder")
_db = None
_tf = None
_lock = threading.Lock()            # 무거운 일은 한 번에 하나(2코어 서버)
_images = {}                        # image_id → dict(img, lines, t)
_renders = {}                       # (fid, w, text) → png bytes


def _engine():
    global _db, _tf
    if _db is None:
        with _lock:
            if _db is None:
                if not os.path.exists(CATALOG):        # 배포 직후 build_catalog.py 를 아직 안 돌린 상태
                    raise FileNotFoundError("폰트 목록이 없습니다: %s — build_catalog.py 를 돌리세요" % CATALOG)
                os.environ.setdefault("FINDER_MAX_STACKS", "30")
                db = E.FontDB(CATALOG)                 # 목록부터 — 실패하면 OCR 모델을 헛되이 올리지 않는다
                _tf = F.TextFinder()
                _db = db
    return _db, _tf


def _ready():
    """엔진을 올린다. 목록이 없거나 못 열면 503 — 화면은 '지금은 자동 찾기를 쓸 수 없어요'로 보여 준다."""
    try:
        return _engine()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, "자동 찾기를 준비하는 중입니다: %s" % e)


def _gc_images():
    now = time.time()
    for k in [k for k, v in _images.items() if now - v["t"] > IMAGE_TTL]:
        _images.pop(k, None)
    while len(_images) > MAX_IMAGES:
        _images.pop(next(iter(_images)), None)


@app.get("/find/health")
def health():
    try:
        db, _ = _engine()
        return {"ok": True, "faces": len(db.items), "images": len(_images)}
    except Exception as e:                                        # 목록이 아직 없으면
        return JSONResponse({"ok": False, "error": str(e)}, status_code=503)


@app.post("/find/detect")
async def detect(image: UploadFile = File(...)):
    raw = await image.read()
    if not raw or len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "이미지는 8MB 까지만 받습니다")
    try:
        im = Image.open(io.BytesIO(raw))
        im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception:
        raise HTTPException(415, "이미지 파일이 아닙니다(JPG·PNG·WEBP)")
    if max(im.size) > MAX_SIDE:
        s = MAX_SIDE / max(im.size)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    img = np.asarray(im)
    db, tf = _ready()
    with _lock:
        lines = tf.find_lines(img)
    lines = [ln for ln in lines if ln["conf"] >= 0.3 and len([c for c in ln["chars"] if E.usable(c[0])]) >= 2]
    image_id = secrets.token_urlsafe(12)
    _gc_images()
    _images[image_id] = dict(img=img, lines=lines, t=time.time())
    return {
        "image_id": image_id, "width": int(img.shape[1]), "height": int(img.shape[0]),
        "lines": [dict(i=i, quad=[[float(x), float(y)] for x, y in ln["quad"]], text=ln["text"], conf=round(float(ln["conf"]), 3))
                  for i, ln in enumerate(lines)],
    }


class MatchReq(BaseModel):
    image_id: str
    line: int
    text: str | None = None          # 사용자가 고친 글자(있으면 이 글자로 자르고 그린다)
    top: int = 8


@app.post("/find/match")
def match(req: MatchReq):
    rec = _images.get(req.image_id)
    if rec is None:
        raise HTTPException(410, "이미지가 지워졌습니다. 다시 올려 주세요")
    if not (0 <= req.line < len(rec["lines"])):
        raise HTTPException(400, "없는 줄입니다")
    ln = rec["lines"][req.line]
    db, tf = _ready()
    chars = [(c[0], c[2]) for c in ln["chars"]]
    base_conf = float(ln["conf"])
    text_override = (req.text or "").strip()[:40] or None
    if text_override:
        chars = _chars_for_text(ln, text_override)
        base_conf = 1.0                                   # 사람이 고친 글자는 다시 읽은 것보다 믿는다
    with _lock:
        r = E.rank_image_ex(db, rec["img"], ln["quad"], chars, top=max(3, min(12, req.top)),
                            ocr=tf.recognize, base_conf=base_conf)
    text = text_override or r.get("text") or ln["text"]
    out = []
    face_of = {(it["fid"], it["weight"]): it for it in db.items}
    for score, fid, w, name in r["shown"][:req.top]:
        info = db.info[fid]
        link = info["link"]
        it = face_of.get((fid, int(w)))
        if info["source"] == "tdtd" and it and it.get("h"):
            # 타닥타닥 폰트정보 페이지(tdtd.io/fonts/about)의 그 폰트 카드로 바로 스크롤 — fontview.js 가 #f= 을 읽는다
            link = TDTD_ABOUT + "#f=" + it["h"]
        out.append(dict(fid=str(fid), w=int(w), name=name, maker=info["maker"], source=info["source"],
                        link=link, why=E.explain_text(r.get("explain", {}).get(fid))))
    return {"text": text, "read": ln["text"], "verdict": r["verdict"], "results": out}


def _chars_for_text(ln, text):
    """사용자가 고친 글자에 맞춘 글자 상자 — 글자 수가 같으면 읽은 상자 자리를 그대로, 아니면 줄 폭을 고르게 나눈다."""
    old = [c for c in ln["chars"] if not c[0].isspace()]
    new = [ch for ch in text if not ch.isspace()]
    if len(old) == len(new):
        return [(ch, c[2]) for ch, c in zip(new, old)]
    q = np.asarray(ln["quad"], float)
    left, right = q[0], q[1]
    lb, rb = q[3], q[2]
    n = max(1, len(new))
    boxes = []
    for k, ch in enumerate(new):
        a, b = k / n, (k + 1) / n
        p0, p1 = left + (right - left) * a, left + (right - left) * b
        p3, p2 = lb + (rb - lb) * a, lb + (rb - lb) * b
        boxes.append((ch, [p0.tolist(), p1.tolist(), p2.tolist(), p3.tolist()]))
    return boxes


@app.get("/find/render")
def render(fid: str, w: int, text: str, h: int = 56):
    db, _ = _ready()
    text = (text or "").strip()[:40] or "폰트"
    h = max(24, min(96, int(h)))
    key = (fid, int(w), text, h)
    png = _renders.get(key)
    if png is None:
        fid_key = int(fid) if fid.isdigit() else fid
        i = next((k for k, it in enumerate(db.items) if it["fid"] == fid_key and it["weight"] == int(w)), None)
        if i is None:
            raise HTTPException(404, "없는 폰트")
        font = db.font(i)
        if font is None:
            raise HTTPException(404, "폰트를 열 수 없습니다")
        f = font.font_variant(size=h)
        width = int(f.getlength(text)) + 24
        im = Image.new("RGBA", (max(48, width), int(h * 1.45)), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((12, int(h * 1.12)), text, font=f, fill=(17, 17, 17, 255), anchor="ls")
        b = io.BytesIO()
        im.save(b, "PNG", optimize=True)
        png = b.getvalue()
        if len(_renders) >= RENDER_CACHE:
            _renders.pop(next(iter(_renders)))
        _renders[key] = png
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
