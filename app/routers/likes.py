"""좋아요 토글 API

- POST /api/fonts/{id}/like   → 좋아요 +1
- DELETE /api/fonts/{id}/like → 좋아요 -1 (취소)

특징:
- 로그인 불필요
- 가벼운 IP rate limit (한 IP당 1초에 1번만 같은 폰트 토글 허용)
  메모리 캐시(in-process) 사용 — 카페24 단일 인스턴스 환경이라 충분.
- like_count는 0 이하로 내려가지 않음 (음수 방지)
"""
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import update
from ..database import get_db
from ..models import Font
from ..schemas import LikeResponse


router = APIRouter(prefix="/api/fonts", tags=["likes"])


# ─── IP rate limit (메모리 캐시) ───────────────────────────
# 한 IP가 같은 폰트를 너무 빠르게 토글하는 것을 방지.
# {(ip, font_id): last_action_timestamp}
_RATE_LIMIT_WINDOW_SECONDS = 1.0  # 1초 안에 같은 폰트 재토글 차단
_recent_actions: dict[tuple[str, int], float] = {}
# 메모리 보호 — 너무 많이 쌓이면 오래된 것 정리
_MAX_CACHE_ENTRIES = 50000


def _client_ip(request: Request) -> str:
    """클라이언트 IP 추출. 카페24가 프록시이므로 X-Forwarded-For 우선."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # "client, proxy1, proxy2" 중 첫 번째가 원본 클라이언트
        return xff.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"


def _check_rate_limit(ip: str, font_id: int) -> None:
    """rate limit 초과 시 429 발생"""
    now = time.time()
    key = (ip, font_id)
    last = _recent_actions.get(key)
    if last and (now - last) < _RATE_LIMIT_WINDOW_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="너무 빠르게 클릭하셨어요. 잠시 후 다시 시도해주세요.",
        )
    _recent_actions[key] = now

    # 메모리 보호 — 너무 많아지면 오래된 것 정리
    if len(_recent_actions) > _MAX_CACHE_ENTRIES:
        threshold = now - 60  # 60초보다 오래된 기록 삭제
        for k, ts in list(_recent_actions.items()):
            if ts < threshold:
                _recent_actions.pop(k, None)


@router.post("/{font_id}/like", response_model=LikeResponse)
def add_like(font_id: int, request: Request, db: Session = Depends(get_db)):
    """좋아요 +1"""
    ip = _client_ip(request)
    _check_rate_limit(ip, font_id)

    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    # 원자적 증가
    db.execute(
        update(Font)
        .where(Font.id == font_id)
        .values(like_count=Font.like_count + 1)
    )
    db.commit()
    db.refresh(font)
    return LikeResponse(font_id=font.id, like_count=font.like_count, liked=True)


@router.delete("/{font_id}/like", response_model=LikeResponse)
def remove_like(font_id: int, request: Request, db: Session = Depends(get_db)):
    """좋아요 취소 (-1). 0 미만으로 내려가지 않음."""
    ip = _client_ip(request)
    _check_rate_limit(ip, font_id)

    font = db.query(Font).filter(Font.id == font_id).first()
    if not font:
        raise HTTPException(status_code=404, detail="폰트를 찾을 수 없습니다")

    if font.like_count > 0:
        db.execute(
            update(Font)
            .where(Font.id == font_id)
            .where(Font.like_count > 0)
            .values(like_count=Font.like_count - 1)
        )
        db.commit()
        db.refresh(font)
    return LikeResponse(font_id=font.id, like_count=font.like_count, liked=False)
