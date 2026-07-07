"""API 요청/응답 스키마 (Pydantic)"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ─────────── Tag ───────────
class TagBase(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    sort_order: Optional[int] = None


class TagOut(TagBase):
    id: int
    sort_order: int
    model_config = ConfigDict(from_attributes=True)


# ─────────── Font ───────────
class FontBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    maker: str = Field(min_length=1, max_length=100)
    weights: str = "1종"
    url: Optional[str] = ""
    stack: str = "'Nanum Gothic',sans-serif"
    is_english: bool = False


class FontCreate(FontBase):
    tags: List[str] = Field(default_factory=list, description="카테고리 이름 배열")
    meta: Dict[str, Any] = Field(default_factory=dict)


class FontUpdate(BaseModel):
    name: Optional[str] = None
    maker: Optional[str] = None
    weights: Optional[str] = None
    url: Optional[str] = None
    stack: Optional[str] = None
    is_english: Optional[bool] = None
    tags: Optional[List[str]] = None
    meta: Optional[Dict[str, Any]] = None
    sort_order: Optional[int] = None


class FontOut(FontBase):
    id: int
    has_file: bool
    sort_order: int
    tags: List[str]  # 이름 배열
    meta: Dict[str, Any] = Field(default_factory=dict)
    like_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class LikeResponse(BaseModel):
    """좋아요 토글 응답"""
    font_id: int
    like_count: int
    liked: bool  # True=방금 +1, False=방금 -1


class FontReorderItem(BaseModel):
    id: int
    sort_order: int


class FontReorderRequest(BaseModel):
    """폰트 정렬 순서 일괄 변경"""
    items: List[FontReorderItem]


# ─────────── Notice ───────────
class NoticeBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = ""
    pinned: bool = False


class NoticeCreate(NoticeBase):
    pass


class NoticeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    pinned: Optional[bool] = None


class NoticeOut(NoticeBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ─────────── Auth ───────────
class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class AuthStatus(BaseModel):
    authenticated: bool
    username: Optional[str] = None
    must_change_password: bool = False


# ─────────── File ───────────
class FileUploadResponse(BaseModel):
    id: int
    file_size: int
    original_size: int
    ratio: float
    format: str = "woff2"
    message: str = ""


# ─────────── FontSubmission (무료폰트 제보) ───────────
class SubmissionOut(BaseModel):
    id: int
    nickname: str
    font_name: str
    content: str
    link: str = ""
    image_path: Optional[str] = None
    status: str
    admin_reply: str = ""
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SubmissionUpdate(BaseModel):
    """관리자 전용 — 상태/답변 수정"""
    status: Optional[str] = None
    admin_reply: Optional[str] = None
