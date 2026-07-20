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
    # 대표 굵기 — 메인 페이지/갤러리 카드에 노출되는 기본 업로드 파일(has_file)의 실제 굵기값.
    # 어드민에서 폰트 등록 시 지정. 100~900 (Thin~Black), 기본 400=Regular.
    primary_weight = Column(Integer, nullable=False, default=400, server_default="400")
    sort_order = Column(Integer, nullable=False, default=0, index=True)
    # 추천 메타데이터 8개 차원 (JSON)
    meta = Column(JSON, default=dict)
    # 전역 좋아요 카운트
    like_count = Column(Integer, nullable=False, default=0, server_default="0")
    # 큐레이터 픽 — 어드민이 직접 지정하는 추천 폰트 (메인 "큐레이터 픽" 섹션 노출용)
    is_pick = Column(Boolean, nullable=False, default=False, server_default="0")
    # ── 웹폰트 CDN 소스 (Google Fonts 등) — 파일 업로드 없이 등록 가능 ──
    # webfont_family가 채워져 있으면 프론트엔드는 로컬 파일 대신
    # webfont_css_url을 로드해서 webfont_family를 font-family로 사용한다.
    # webfont_weights는 콤마로 구분된 굵기 목록 문자열(예: "300,400,700,900")로 저장.
    webfont_family = Column(String(200), nullable=True)
    webfont_css_url = Column(String(500), nullable=True)
    webfont_weights = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 관계
    tags = relationship("Tag", secondary="font_tags", back_populates="fonts", lazy="joined")
    extra_weights = relationship(
        "FontWeight", back_populates="font",
        cascade="all, delete-orphan", lazy="joined",
        order_by="FontWeight.weight",
    )

    __table_args__ = (