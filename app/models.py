"""DB 테이블 정의 (의뢰서 2장의 데이터 모델과 일치)

테이블: fonts, tags, font_tags, notices, admin_users, font_likes(선택)
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, ForeignKey,
    UniqueConstraint, Index, JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


# 폰트와 카테고리의 다대다 관계 테이블
class FontTag(Base):
    __tablename__ = "font_tags"
    font_id = Column(Integer, ForeignKey("fonts.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class Font(Base):
    __tablename__ = "fonts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    maker = Column(String(100), nullable=False)
    weights = Column(String(20), default="1종")
    url = Column(String(500))
    stack = Column(String(200), default="'Nanum Gothic',sans-serif")
    is_english = Column(Boolean, default=False)
    has_file = Column(Boolean, default=False)
    sort_order = Column(Integer, nullable=False, default=0, index=True)
    # 추천 메타데이터 8개 차원 (JSON)
    meta = Column(JSON, default=dict)
    # 전역 좋아요 카운트
    like_count = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 관계
    tags = relationship("Tag", secondary="font_tags", back_populates="fonts", lazy="joined")

    __table_args__ = (
        Index("idx_fonts_sort", "sort_order"),
        Index("idx_fonts_likes", "like_count"),
    )


class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())

    fonts = relationship("Font", secondary="font_tags", back_populates="tags")


class Notice(Base):
    __tablename__ = "notices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    # HTML 본문 (B/STRONG/BR/P/DIV만 허용, 서버에서 sanitize)
    content = Column(Text, nullable=False, default="")
    pinned = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    # bcrypt 해시
    password_hash = Column(String(200), nullable=False)
    # 첫 로그인 시 강제 비밀번호 변경 플래그
    must_change_password = Column(Boolean, default=True)
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
