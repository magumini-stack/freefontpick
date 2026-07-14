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
        Index("idx_fonts_sort", "sort_order"),
        Index("idx_fonts_likes", "like_count"),
    )


class FontWeight(Base):
    """폰트별 추가 굵기 파일 (어드민에서 개별 업로드).

    - 대표 굵기(fonts.primary_weight)와 별개로, 폰트 하나에 여러 굵기를
      추가로 등록할 수 있다. 각 굵기는 자체 woff2 파일을 가진다.
    - 실제 파일은 files.py의 weight_file_path()가 정하는 경로
      (/app/user_data/fonts/font-{id:03d}-w{weight}.woff2)에 저장되고,
      이 테이블은 메타데이터(굵기값·라벨)만 관리한다.
    - 상세페이지 굵기별 보기 / 디자인 모달 굵기 박스는 모두
      GET /api/fonts/{id}/weights 하나를 통해 이 테이블 + 기존 매니페스트
      기반 굵기를 합쳐서 받는다.
    """
    __tablename__ = "font_weights"
    id = Column(Integer, primary_key=True, autoincrement=True)
    font_id = Column(Integer, ForeignKey("fonts.id", ondelete="CASCADE"), nullable=False)
    weight = Column(Integer, nullable=False)
    label = Column(String(30), nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())

    font = relationship("Font", back_populates="extra_weights")

    __table_args__ = (
        UniqueConstraint("font_id", "weight", name="uq_font_weight"),
        Index("idx_font_weights_font", "font_id"),
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


class FontSubmission(Base):
    """무료폰트 제보 게시판 — '폰트 찾기'.

    로그인 없이 누구나 질문 작성 가능. 이미지 1장 첨부 가능.
    답변도 로그인 없이 누구나 작성 가능(SubmissionAnswer). 관리자는 삭제만 관리.
    status/admin_reply 컬럼은 과거 "관리자 전용 답변" 방식의 잔재로, 하위 호환을 위해
    컬럼은 유지하되 더 이상 UI에서 사용하지 않는다.
    """
    __tablename__ = "font_submissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    nickname = Column(String(50), nullable=False, default="익명")
    font_name = Column(String(100), nullable=False)
    content = Column(Text, nullable=False, default="")
    link = Column(String(500), default="")
    image_path = Column(String(300))  # 저장된 이미지 파일명 (상대경로)
    status = Column(String(20), nullable=False, default="pending")  # 더 이상 사용 안 함 (하위호환)
    admin_reply = Column(Text, default="")  # 더 이상 사용 안 함 (하위호환) — SubmissionAnswer로 대체
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    answers = relationship(
        "SubmissionAnswer", back_populates="submission",
        cascade="all, delete-orphan", lazy="joined",
        order_by="SubmissionAnswer.created_at",
    )

    __table_args__ = (
        Index("idx_submissions_created", "created_at"),
    )


class SubmissionAnswer(Base):
    """'폰트 찾기' 질문에 달리는 답변 — 로그인 없이 누구나 작성 가능.

    관리자는 부적절한 답변을 삭제만 할 수 있다 (수정 권한 없음).
    """
    __tablename__ = "submission_answers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("font_submissions.id", ondelete="CASCADE"), nullable=False)
    nickname = Column(String(50), nullable=False, default="익명")
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())

    submission = relationship("FontSubmission", back_populates="answers")

    __table_args__ = (
        Index("idx_submission_answers_submission", "submission_id"),
    )


class FontPairing(Base):
    """폰트 페어링 조합 (제목 폰트 + 본문 폰트).

    - 시드는 pairing_data.PAIRING_SEED에서 이름 매칭으로 삽입 (seed.py)
    - 폰트가 삭제되면 조합도 함께 삭제 (CASCADE)
    - title_weight/body_weight: 페어링 카드에서 사용할 굵기 (v5에서 도입)
      · 굵기 파일이 있는 폰트만 실제로 반영됨. 없는 폰트는 기본 굵기로 폴백.
      · 400=Regular, 500=Medium, 700=Bold, 800=ExtraBold, 900=Heavy
    """
    __tablename__ = "font_pairings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    theme = Column(String(50), nullable=False)
    title_font_id = Column(Integer, ForeignKey("fonts.id", ondelete="CASCADE"), nullable=False)
    body_font_id = Column(Integer, ForeignKey("fonts.id", ondelete="CASCADE"), nullable=False)
    sample_title = Column(String(100), nullable=False, default="")
    sample_body = Column(String(200), nullable=False, default="")
    description = Column(String(300), nullable=False, default="")
    title_weight = Column(Integer, nullable=False, default=700, server_default="700")
    body_weight = Column(Integer, nullable=False, default=400, server_default="400")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())

    title_font = relationship("Font", foreign_keys=[title_font_id], lazy="joined")
    body_font = relationship("Font", foreign_keys=[body_font_id], lazy="joined")

    __table_args__ = (
        Index("idx_pairings_title", "title_font_id"),
        Index("idx_pairings_body", "body_font_id"),
    )


class AppMeta(Base):
    """앱 내부 메타 (시드 버전 등 키-값 저장)"""
    __tablename__ = "app_meta"
    key = Column(String(50), primary_key=True)
    value = Column(String(200), nullable=False, default="")
