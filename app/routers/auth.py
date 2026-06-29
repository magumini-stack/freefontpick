"""인증 API: 로그인, 로그아웃, 상태 조회, 비밀번호 변경"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import AdminUser
from ..auth import (
    hash_password, verify_password, get_current_admin, get_optional_admin,
)
from ..schemas import LoginRequest, PasswordChangeRequest, AuthStatus

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=AuthStatus)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(AdminUser.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다",
        )
    user.last_login_at = datetime.utcnow()
    db.commit()
    request.session["admin_user_id"] = user.id
    return AuthStatus(
        authenticated=True,
        username=user.username,
        must_change_password=user.must_change_password,
    )


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/status", response_model=AuthStatus)
def status_(admin = Depends(get_optional_admin)):
    if not admin:
        return AuthStatus(authenticated=False)
    return AuthStatus(
        authenticated=True,
        username=admin.username,
        must_change_password=admin.must_change_password,
    )


@router.post("/change-password", response_model=AuthStatus)
def change_password(
    payload: PasswordChangeRequest,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="현재 비밀번호가 올바르지 않습니다",
        )
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="새 비밀번호는 현재 비밀번호와 달라야 합니다",
        )
    admin.password_hash = hash_password(payload.new_password)
    admin.must_change_password = False
    db.commit()
    return AuthStatus(
        authenticated=True,
        username=admin.username,
        must_change_password=False,
    )
