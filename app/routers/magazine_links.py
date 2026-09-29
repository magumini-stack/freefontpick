"""매거진에 거는 티스토리 글 — 주소만 넣으면 대표 사진·제목을 채운다 (2026-09-29).

  GET    /api/magazine-links                  목록 (공개)
  GET    /api/magazine-links/{id}/thumb       대표 사진 (받아 둔 파일)
  POST   /api/admin/magazine-links            {url} 로 추가 — 관리자
  POST   /api/admin/magazine-links/{id}/refresh  글을 다시 읽어 제목·사진 갱신 — 관리자
  PATCH  /api/admin/magazine-links/{id}       {sort_order} — 관리자
  DELETE /api/admin/magazine-links/{id}       — 관리자

글 정보는 글 페이지의 og 태그(og:title · og:image · og:description ·
article:published_time)에서 읽는다. 티스토리는 이 넷을 늘 채워 둔다.

대표 사진은 받아서 /app/user_data/magazine_thumbs 에 둔다. og:image 주소에
만료 서명(expires=…)이 붙어 있어 그대로 걸면 하루 뒤 깨진다(2026-09-29 실측).

주소는 *.tistory.com 만 받는다. 관리자만 부르는 기능이지만, 서버가 남의 주소를
대신 받아 오는 구조라 아무 주소나 받으면 서버 안쪽 주소를 찌르는 통로가 된다.
"""
import html as _html
import io
import os
import re
import urllib.request
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_password_changed
from ..database import get_db
from ..models import MagazineLink

router = APIRouter(tags=["magazine-links"])

THUMB_DIR = Path(os.getenv("MAGAZINE_THUMB_DIR", "/app/user_data/magazine_thumbs"))
THUMB_WIDTH = 800
_UA = "Mozilla/5.0 (compatible; FreeFontPick/1.0; +https://freefontpick.tdtd.io)"
_MAX_HTML = 3 * 1024 * 1024
_MAX_IMG = 15 * 1024 * 1024


class LinkIn(BaseModel):
    url: str


class LinkPatch(BaseModel):
    sort_order: Optional[int] = None


class LinkOut(BaseModel):
    id: int
    url: str
    title: str
    description: str
    published: str
    thumb: str
    sort_order: int


def _out(r: MagazineLink) -> LinkOut:
    thumb = f"/api/magazine-links/{r.id}/thumb?v={r.image_file}" if r.image_file else ""
    return LinkOut(id=r.id, url=r.url, title=r.title, description=r.description,
                   published=r.published, thumb=thumb, sort_order=r.sort_order)


def ordered(db: Session) -> List[MagazineLink]:
    return (db.query(MagazineLink)
            .order_by(MagazineLink.sort_order, MagazineLink.id.desc()).all())


def normalize_url(raw: str) -> str:
    """https://blog.tistory.com/123 꼴로 맞춘다. 모바일 주소(/m/123)도 PC 주소로."""
    u = (raw or "").strip()
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    parts = urlsplit(u)
    host = (parts.hostname or "").lower()
    if not (host == "tistory.com" or host.endswith(".tistory.com")):
        raise HTTPException(status_code=400, detail="티스토리(…tistory.com) 글 주소만 넣을 수 있습니다")
    path = re.sub(r"^/m/", "/", parts.path or "/")
    return urlunsplit(("https", host, path, "", ""))


def _get(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=400, detail="글 또는 사진이 너무 큽니다")
    return data


def _meta(html: str, key: str) -> str:
    """<meta property|name="key" content="…"> 의 값. 속성 순서가 바뀌어도 찾는다."""
    for pat in (
        r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']*)["\']',
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']%s["\']',
    ):
        m = re.search(pat % re.escape(key), html, re.I)
        if m:
            return _html.unescape(m.group(1)).strip()
    return ""


def read_post(url: str) -> dict:
    try:
        raw = _get(url, _MAX_HTML)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"글을 열 수 없습니다: {e}")
    html = raw.decode("utf-8", "replace")
    title = _meta(html, "og:title")
    if not title:
        m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        title = _html.unescape(m.group(1)).strip() if m else ""
    if not title:
        raise HTTPException(status_code=400, detail="글 제목을 찾지 못했습니다. 글 주소가 맞는지 확인해 주세요")
    return {
        "title": title[:300],
        "description": (_meta(html, "og:description") or _meta(html, "description"))[:500],
        "image": _meta(html, "og:image"),
        "published": _meta(html, "article:published_time")[:10],
    }


def save_thumb(image_url: str, link_id: int) -> str:
    """대표 사진을 받아 폭 800px JPEG 로 저장하고 파일 이름을 돌려준다. 없으면 ''."""
    if not image_url or not image_url.startswith(("http://", "https://")):
        return ""
    try:
        data = _get(image_url, _MAX_IMG)
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        if im.width > THUMB_WIDTH:
            im = im.resize((THUMB_WIDTH, round(im.height * THUMB_WIDTH / im.width)))
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        # 이름에 시각을 넣어 갱신하면 주소가 바뀌게 한다 — 사진은 1년 캐시한다.
        import time
        name = f"{link_id}-{int(time.time())}.jpg"
        im.save(THUMB_DIR / name, "JPEG", quality=85, optimize=True)
        return name
    except Exception as e:
        print(f"[magazine] 대표 사진 저장 실패 id={link_id}: {type(e).__name__}: {e}", flush=True)
        return ""


def _drop_file(name: str):
    if name:
        try:
            (THUMB_DIR / name).unlink()
        except OSError:
            pass


@router.get("/api/magazine-links", response_model=List[LinkOut])
def list_links(db: Session = Depends(get_db)):
    return [_out(r) for r in ordered(db)]


@router.get("/api/magazine-links/{link_id}/thumb")
def link_thumb(link_id: int, db: Session = Depends(get_db)):
    r = db.query(MagazineLink).filter(MagazineLink.id == link_id).first()
    if r is None or not r.image_file:
        raise HTTPException(status_code=404, detail="사진이 없습니다")
    path = THUMB_DIR / r.image_file
    if not path.is_file():
        raise HTTPException(status_code=404, detail="사진이 없습니다")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.post("/api/admin/magazine-links", response_model=LinkOut)
def add_link(body: LinkIn, db: Session = Depends(get_db),
             _admin=Depends(require_password_changed)):
    url = normalize_url(body.url)
    if db.query(MagazineLink).filter(MagazineLink.url == url).first():
        raise HTTPException(status_code=409, detail="이미 등록된 글입니다")
    info = read_post(url)
    # 새 글은 맨 앞에 선다.
    first = db.query(MagazineLink).order_by(MagazineLink.sort_order).first()
    r = MagazineLink(url=url, title=info["title"], description=info["description"],
                     published=info["published"],
                     sort_order=(first.sort_order - 10) if first else 0)
    db.add(r)
    db.flush()
    r.image_file = save_thumb(info["image"], r.id)
    db.commit()
    db.refresh(r)
    return _out(r)


@router.post("/api/admin/magazine-links/{link_id}/refresh", response_model=LinkOut)
def refresh_link(link_id: int, db: Session = Depends(get_db),
                 _admin=Depends(require_password_changed)):
    r = db.query(MagazineLink).filter(MagazineLink.id == link_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="없는 글입니다")
    info = read_post(r.url)
    r.title, r.description, r.published = info["title"], info["description"], info["published"]
    new_file = save_thumb(info["image"], r.id)
    if new_file:
        _drop_file(r.image_file)
        r.image_file = new_file
    db.commit()
    db.refresh(r)
    return _out(r)


@router.patch("/api/admin/magazine-links/{link_id}", response_model=LinkOut)
def patch_link(link_id: int, body: LinkPatch, db: Session = Depends(get_db),
               _admin=Depends(require_password_changed)):
    r = db.query(MagazineLink).filter(MagazineLink.id == link_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="없는 글입니다")
    if body.sort_order is not None:
        r.sort_order = body.sort_order
    db.commit()
    db.refresh(r)
    return _out(r)


@router.delete("/api/admin/magazine-links/{link_id}")
def delete_link(link_id: int, db: Session = Depends(get_db),
                _admin=Depends(require_password_changed)):
    r = db.query(MagazineLink).filter(MagazineLink.id == link_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="없는 글입니다")
    _drop_file(r.image_file)
    db.delete(r)
    db.commit()
    return {"ok": True}
