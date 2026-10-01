"""전체 폰트 보기 첫 줄에 고정할 타닥타닥 구독 폰트 — 관리자가 고른다 (2026-10-01).

  GET /api/subscribe-picks          {"picks": ["<h>", …]} (공개)
  PUT /api/admin/subscribe-picks    {"picks": ["<h>", …]} — 관리자

<h> 는 static/subfonts/fonts.json 의 폰트 웹폰트 표식(10자리 16진수)이다.
tdtd-webfont 가 제작사 폴더·굵기·PS 이름으로 만들어서 다시 구워도 바뀌지 않는다.
따로 표를 만들지 않고 AppMeta 한 줄(쉼표로 이음)에 둔다.
"""
import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_password_changed
from ..database import get_db
from ..models import AppMeta

router = APIRouter(tags=["subscribe-picks"])

KEY = "subscribe_pin_picks"
MAX_PICKS = 4          # 첫 줄 고정 칸 수 (ffp-subscribe.js 의 pick(4))
_H = re.compile(r"^[0-9a-f]{10}$")


class Picks(BaseModel):
    picks: List[str]


def read_picks(db: Session) -> List[str]:
    row = db.query(AppMeta).filter(AppMeta.key == KEY).first()
    return [h for h in (row.value.split(",") if row and row.value else []) if _H.match(h)]


@router.get("/api/subscribe-picks", response_model=Picks)
def get_picks(db: Session = Depends(get_db)):
    return Picks(picks=read_picks(db))


@router.put("/api/admin/subscribe-picks", response_model=Picks)
def put_picks(body: Picks, db: Session = Depends(get_db), _=Depends(require_password_changed)):
    picks = []
    for h in body.picks:
        h = (h or "").strip().lower()
        if not _H.match(h):
            raise HTTPException(status_code=400, detail=f"알 수 없는 폰트 표식입니다: {h}")
        if h not in picks:
            picks.append(h)
    if len(picks) > MAX_PICKS:
        raise HTTPException(status_code=400, detail=f"최대 {MAX_PICKS}개까지 고를 수 있습니다")
    row = db.query(AppMeta).filter(AppMeta.key == KEY).first()
    if row is None:
        row = AppMeta(key=KEY, value="")
        db.add(row)
    row.value = ",".join(picks)
    db.commit()
    return Picks(picks=picks)
