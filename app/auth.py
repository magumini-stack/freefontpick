"""세션 기반 관리자 인증

- bcrypt(직접)로 비밀번호 해시
- 쿠키 세션 (itsdangerous SessionMiddleware 사용)
- 첫 로그인 시 must_change_password=True → 비번 변경 강제

passlib는 Python 3.12 + 최신 bcrypt 조합에서 버그가 있어 bcrypt를 직접 사용.
"""
from typing import Optional
import bcrypt
from fastapi import HTTPException, Request, Depends, status
from sqlalchemy.orm import Session
from .database import get_db
from .models import AdminUser


def hash_password(plain: str) -> str:
    """비밀번호를 bcrypt 해시로 변환. 72바이트 초과 시 잘라냄(bcrypt 제한)."""
    if isinstance(plain, str):
        plain_bytes = plain.encode("utf-8")
    else:
        plain_bytes = plain
    if len(plain_bytes) > 72:
        plain_bytes = plain_bytes[:72]
    return bcrypt.hashpw(plain_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        if isinstance(plain, str):
            plain_bytes = plain.encode("utf-8")
        else:
            plain_bytes = plain
        if len(plain_bytes) > 72:
            plain_bytes = plain_bytes[:72]
        if isinstance(hashed, str):
            hashed_bytes = hashed.encode("utf-8")
        else:
            hashed_bytes = hashed
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception:
        return False


def get_current_admin(
    request: Request,
    db: Session = Depends(get_db),
) -> AdminUser:
    """현재 세션의 관리자 반환. 없으면 401."""
    user_id = request.session.get("admin_user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
        )
    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not user:
        # 세션은 있는데 유저가 사라진 경우 (DB 리셋 등)
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 세션입니다. 다시 로그인해주세요.",
        )
    return user


def require_password_changed(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
    """비밀번호 변경 강제 — 변경 안 했으면 403."""
    if admin.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="처음 로그인하셨습니다. 비밀번호를 먼저 변경해주세요.",
        )
    return admin


def get_optional_admin(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[AdminUser]:
    """관리자 세션이 있으면 반환, 없으면 None (인증 선택적)"""
    user_id = request.session.get("admin_user_id")
    if not user_id:
        return None
    return db.query(AdminUser).filter(AdminUser.id == user_id).first()
