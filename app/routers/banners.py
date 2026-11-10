"""타닥타닥 배너 관리 — 메인(쓰는 자리 바 아래)·전체 무료폰트(목록 위)에서 6초마다 번갈아 나오는 그림 (2026-11-10).

사용자님: "서버에서 배포해야 해?… 관리자 페이지에서 배너 바꿀 수 있게 아예 바꾸자".
전에는 그림·링크·문구가 코드(design.py · static/fonts.html)에 박혀 있어 배너를 바꿀 때마다 배포해야 했다.
이제 관리자 '배너 관리' 탭(static/admin.html)에서 올리고 고치면 다음 요청부터 바로 보인다.

- 자리(spot): home(메인) · fonts(전체 무료폰트). 한 배너를 두 자리에 함께 걸 수 있다.
- 그림 두 장: PC 1200×140, 휴대폰 720×364 비율. 올리면 2배 크기(2400×280 · 1440×728) WebP 로 맞춰 굽는다.
  비율이 3% 넘게 다르면 받지 않는다 — 잘라 내면 그림 속 글자가 잘린다.
  올린 그림은 /app/user_data/banners 에 두고 /media/banners/<이름> 으로 낸다(이름에 시각이 들어가 오래 캐시해도 된다).
- 클릭은 track.py 가 'tdtd_ad' 로 센다. 자리 이름 = spot(+ '_' + track). 처음 옮겨 온 구독 배너는 track 'sub'
  → 옛 기록 이름(home·fonts)을 그대로 잇는다. 새 배너는 'b<id>'.
- 처음 시작할 때 지금 걸려 있던 배너 세 장(구독 · 오늘의기록 · 글자로 노는 앱)을 표로 옮긴다(seed_defaults).
"""
import io
import os
import re
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import require_password_changed
from ..database import get_db
from ..models import AppMeta, SiteBanner

router = APIRouter(tags=["banners"])

BANNERS_DIR = Path(os.getenv("BANNERS_DIR", "/app/user_data/banners"))
SPOTS = {"home": "메인", "fonts": "전체 무료폰트"}
SIZE = {"pc": (2400, 280), "m": (1440, 728)}     # 2배 그림. 화면에는 1200×140 · 720×364 로 그린다
MAX_UPLOAD = 8 * 1024 * 1024
SEEDED_KEY = "site_banners_seeded_20261110"
_NAME_RE = re.compile(r"^banner-\d+-(pc|m)-\d+\.webp$")

_cache = {"ver": 0, "rows": None}   # 공개 화면용 — 고치면 비운다(요청마다 DB 를 묻지 않게)


def _esc(s: str) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def spot_key(spot: str, track: str) -> str:
    """클릭 기록에 쓰는 자리 이름(track.py · stats.py)."""
    return spot if track in ("", "sub") else f"{spot}_{track}"


def _out(b: SiteBanner) -> dict:
    return {"id": b.id, "name": b.name, "link": b.link, "alt": b.alt, "pc_url": b.pc_url, "m_url": b.m_url,
            "spots": [s for s in (b.spots or "").split(",") if s], "track": b.track,
            "sort_order": b.sort_order, "is_active": bool(b.is_active),
            "keys": {s: spot_key(s, b.track) for s in (b.spots or "").split(",") if s}}


def _active_rows(db: Session) -> List[dict]:
    if _cache["rows"] is None:
        rows = (db.query(SiteBanner).filter(SiteBanner.is_active.is_(True))
                .order_by(SiteBanner.sort_order, SiteBanner.id).all())
        _cache["rows"] = [_out(b) for b in rows]
    return _cache["rows"]


def _touch():
    _cache["rows"] = None


def roll_items(db: Session, spot: str) -> str:
    """그 자리의 배너 <a> 들. 감싸는 div(.ad-roll)와 번갈아 넘기는 스크립트는 부르는 쪽(design.py·fonts.html)에 있다.
    첫 장에 class="on" — 스크립트가 무작위로 다시 고른다. 실패하면 빈 문자열(배너 자리만 비고 페이지는 뜬다)."""
    try:
        rows = [b for b in _active_rows(db) if spot in b["spots"] and b["pc_url"] and b["m_url"]]
    except Exception:
        return ""
    out = []
    for i, b in enumerate(rows):
        on = ' class="on"' if i == 0 else ""
        out.append(
            f'<a{on} data-tdtd-ad="{_esc(b["keys"][spot])}" href="{_esc(b["link"])}" '
            'target="_blank" rel="noopener"><picture>'
            f'<source media="(max-width:640px)" srcset="{_esc(b["m_url"])}" width="720" height="364">'
            f'<img src="{_esc(b["pc_url"])}" width="1200" height="140" decoding="async" alt="{_esc(b["alt"])}">'
            '</picture></a>')
    return "".join(out)


def known_keys(db: Session) -> dict:
    """클릭 기록 자리 이름 → 통계에 보일 이름. 지금 표에 있는 배너(꺼진 것 포함)."""
    out = {}
    for b in db.query(SiteBanner).order_by(SiteBanner.sort_order, SiteBanner.id).all():
        for s in (b.spots or "").split(","):
            if s in SPOTS:
                out[spot_key(s, b.track)] = f"{SPOTS[s]} · {b.name}" + ("" if b.is_active else " (꺼 둠)")
    return out


# ── 처음 옮기기 ───────────────────────────────────────────────────────
def seed_defaults(db: Session):
    """11/10 까지 코드에 박혀 있던 배너를 표로 옮긴다(한 번만). 그 뒤로는 관리자 화면이 정본이다."""
    if db.query(AppMeta).filter(AppMeta.key == SEEDED_KEY).first():
        return
    if not db.query(SiteBanner).first():
        db.add_all([
            SiteBanner(name="타닥타닥 구독", link="https://tdtd.io/", spots="home,fonts", track="sub", sort_order=1,
                       pc_url="/static/ads/tdtd-sub-pc-slim-v3.webp", m_url="/static/ads/tdtd-sub-m-slim-v3.webp",
                       alt="타닥타닥 폰트 구독 서비스 — 월 6,600원으로 타닥타닥 폰트 전종을 라이선스 제한 없이 사용하세요. 구독 알아보기"),
            SiteBanner(name="오늘의기록 출시", link="https://tdtd.io/todaystamp.html", spots="home", track="todaystamp",
                       sort_order=2, pc_url="/static/ads/tdtd-todaystamp-pc-v3.webp",
                       m_url="/static/ads/tdtd-todaystamp-m-v3.webp",
                       alt="와이즈폰트 새 앱 오늘의기록 — 감성 카메라로 찍고, 사진을 오늘의 기록으로 남겨요. "
                           "타임스탬프 카메라와 포토 다이어리를 하나로. 앱 다운로드"),
            SiteBanner(name="글자로 노는 앱", link="https://tdtd.io/apps.html", spots="fonts", track="apps", sort_order=3,
                       pc_url="/static/ads/tdtd-apps-pc-slim-v3.webp", m_url="/static/ads/tdtd-apps-m-slim-v3.webp",
                       alt="글자로 노는 앱, 지금 다운 받으세요 — 와이즈폰트 무료 앱 5종: 캘리공방 · 글씨사진관 · 움짤공방 · "
                           "폰트박스 · 흐어어 메모장. 앱 다운로드"),
        ])
    db.add(AppMeta(key=SEEDED_KEY, value="1"))
    db.commit()
    _touch()


# ── 그림 ─────────────────────────────────────────────────────────────
def _bake(raw: bytes, kind: str, banner_id: int) -> str:
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:
        raise HTTPException(400, "그림 파일을 읽을 수 없어요. PNG·JPG·WebP 로 올려 주세요.")
    tw, th = SIZE[kind]
    if abs(im.width / im.height - tw / th) > 0.03 * (tw / th):
        half = f"{tw // 2}×{th // 2}"
        raise HTTPException(400, f"{'PC' if kind == 'pc' else '휴대폰'} 그림 비율이 맞지 않아요. "
                                 f"{half}(또는 {tw}×{th}) 비율로 올려 주세요. 지금 그림 {im.width}×{im.height}")
    im = im.convert("RGB").resize((tw, th), Image.LANCZOS)
    BANNERS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"banner-{banner_id}-{kind}-{int(time.time() * 1000)}.webp"
    im.save(BANNERS_DIR / name, "WEBP", quality=88, method=6)
    return f"/media/banners/{name}"


def _drop_file(url: str):
    """올려 둔 그림만 지운다(/static/ads 의 옛 그림은 저장소 파일이라 두고)."""
    if url.startswith("/media/banners/"):
        name = url.rsplit("/", 1)[-1]
        if _NAME_RE.match(name):
            try:
                (BANNERS_DIR / name).unlink()
            except FileNotFoundError:
                pass


@router.get("/media/banners/{name}", include_in_schema=False)
def banner_file(name: str):
    p = BANNERS_DIR / name
    if not _NAME_RE.match(name) or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ── 관리자 API ────────────────────────────────────────────────────────
def _spots(s: str) -> str:
    got = [x for x in (s or "").split(",") if x in SPOTS]
    return ",".join(dict.fromkeys(got))


async def _read(f: Optional[UploadFile]) -> Optional[bytes]:
    if f is None or not getattr(f, "filename", ""):
        return None
    raw = await f.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "그림이 너무 커요. 8MB 아래로 올려 주세요.")
    return raw or None


@router.get("/api/admin/banners")
def list_banners(_admin=Depends(require_password_changed), db: Session = Depends(get_db)):
    seed_defaults(db)
    rows = db.query(SiteBanner).order_by(SiteBanner.sort_order, SiteBanner.id).all()
    return {"spots": SPOTS, "size": {"pc": "1200×140", "m": "720×364"}, "banners": [_out(b) for b in rows]}


@router.post("/api/admin/banners")
async def create_banner(name: str = Form(...), link: str = Form(...), alt: str = Form(""), spots: str = Form("home"),
                        is_active: bool = Form(True), pc: UploadFile = File(...), m: UploadFile = File(...),
                        _admin=Depends(require_password_changed), db: Session = Depends(get_db)):
    pc_raw, m_raw = await _read(pc), await _read(m)
    if not pc_raw or not m_raw:
        raise HTTPException(400, "PC 그림과 휴대폰 그림을 모두 올려 주세요.")
    if not link.strip().startswith(("https://", "http://", "/")):
        raise HTTPException(400, "링크는 https:// 로 시작하는 주소로 넣어 주세요.")
    top = db.query(SiteBanner).order_by(SiteBanner.sort_order.desc()).first()
    b = SiteBanner(name=name.strip()[:60] or "배너", link=link.strip()[:500], alt=(alt.strip() or name.strip())[:300],
                   spots=_spots(spots) or "home", is_active=is_active, sort_order=(top.sort_order + 1 if top else 1))
    db.add(b)
    db.flush()
    b.track = f"b{b.id}"
    b.pc_url = _bake(pc_raw, "pc", b.id)
    b.m_url = _bake(m_raw, "m", b.id)
    db.commit()
    _touch()
    return _out(b)


@router.put("/api/admin/banners/{banner_id}")
async def update_banner(banner_id: int, name: str = Form(...), link: str = Form(...), alt: str = Form(""),
                        spots: str = Form("home"), is_active: bool = Form(True),
                        pc: Optional[UploadFile] = File(None), m: Optional[UploadFile] = File(None),
                        _admin=Depends(require_password_changed), db: Session = Depends(get_db)):
    b = db.get(SiteBanner, banner_id)
    if not b:
        raise HTTPException(404, "배너가 없어요.")
    if not link.strip().startswith(("https://", "http://", "/")):
        raise HTTPException(400, "링크는 https:// 로 시작하는 주소로 넣어 주세요.")
    pc_raw, m_raw = await _read(pc), await _read(m)
    new_pc = _bake(pc_raw, "pc", b.id) if pc_raw else None
    new_m = _bake(m_raw, "m", b.id) if m_raw else None
    if new_pc:
        _drop_file(b.pc_url); b.pc_url = new_pc
    if new_m:
        _drop_file(b.m_url); b.m_url = new_m
    b.name = name.strip()[:60] or b.name
    b.link = link.strip()[:500]
    b.alt = (alt.strip() or b.name)[:300]
    b.spots = _spots(spots) or b.spots
    b.is_active = is_active
    db.commit()
    _touch()
    return _out(b)


@router.post("/api/admin/banners/reorder")
def reorder_banners(ids: List[int], _admin=Depends(require_password_changed), db: Session = Depends(get_db)):
    for i, bid in enumerate(ids, 1):
        b = db.get(SiteBanner, bid)
        if b:
            b.sort_order = i
    db.commit()
    _touch()
    return {"ok": True}


@router.delete("/api/admin/banners/{banner_id}", status_code=204)
def delete_banner(banner_id: int, _admin=Depends(require_password_changed), db: Session = Depends(get_db)):
    b = db.get(SiteBanner, banner_id)
    if not b:
        raise HTTPException(404, "배너가 없어요.")
    _drop_file(b.pc_url); _drop_file(b.m_url)
    db.delete(b)
    db.commit()
    _touch()
