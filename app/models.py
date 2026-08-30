"""DB 테이블 정의 (의뢰서 2장의 데이터 모델과 일치)

테이블: fonts, tags, font_tags, notices, admin_users, font_likes(선택)
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey,
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
    # 태그 축: 'use'(용도) | 'shape'(모양) | 'mood'(느낌). NULL = 미분류
    axis = Column(String(10), nullable=True)
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


class PreviewPhrase(Base):
    """미리보기 문구 프리셋 — '문구 미리보기로 추천 받기' 기능.

    Font.meta와 동일한 8차원(mood/usage/industry/personality/weight_feel/
    formality/reading_length) 구조를 tags에 그대로 저장해서, 프론트의
    scoreFont()를 수정 없이 재사용할 수 있게 한다.
    어드민에서 추가/수정/삭제/노출여부/순서 편집 가능.
    """
    __tablename__ = "preview_phrases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(String(100), nullable=False)
    tags = Column(JSON, default=dict)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class FontView(Base):
    """상세페이지 조회수 — 날짜별로 한 칸씩.

    누적 한 칸으로 두면 "최근 7일"을 낼 수 없다. 오래전에 올라온 폰트가
    영원히 상위를 차지해 '실시간'이 아니게 된다. 그래서 날짜로 쪼갠다.

    세는 규칙은 app/font_views.py 에 있다 — 봇과 새로고침을 거른다.
    안 거르면 상세페이지가 222장이라 순위를 크롤러가 정한다.

    운영은 MySQL, 로컬은 SQLite다. 양쪽에서 도는 타입만 쓴다.
    """
    __tablename__ = "font_views"
    font_id = Column(Integer, ForeignKey("fonts.id", ondelete="CASCADE"),
                     primary_key=True)
    day = Column(Date, primary_key=True)
    count = Column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        # 최근 N일을 날짜로 훑으므로 날짜에 인덱스를 둔다
        Index("ix_font_views_day", "day"),
    )


class PageView(Base):
    """폰트 상세 말고 다른 페이지의 조회수 — 날짜별로 한 칸씩.

    FontView 와 나눠 둔 이유
    ----------------------
    FontView 는 font_id 가 fonts 를 참조하는 외래키다. 용도 허브(slug)나 조합
    페이지처럼 폰트가 아닌 것을 거기 담을 수 없다. 그렇다고 FontView 를
    범용으로 고치면 인기 순위 계산이 걸려 있어 위험하다 — 그쪽은 손대지 않고
    새 표를 옆에 둔다.

        kind  무엇의 조회인가. 'use'(용도 허브) · 'pair'(폰트 조합)
        key   그 안에서 무엇인가. 허브는 slug, 조합 페이지는 빈 문자열
        day   날짜
        count 그날 몇 번

    세는 규칙은 app/font_views.py 와 같다 — 봇과 30분 내 새로고침을 거른다.

    운영은 MySQL, 로컬은 SQLite다. 양쪽에서 도는 타입만 쓴다.
    """
    __tablename__ = "page_views"
    kind = Column(String(20), primary_key=True)
    # 빈 문자열도 키가 되므로 nullable 이 아니다. MySQL 은 인덱스가 붙는
    # 문자열 기본키 길이를 제한하므로 넉넉하되 짧게 잡는다.
    key = Column(String(120), primary_key=True, default="", server_default="")
    day = Column(Date, primary_key=True)
    count = Column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        Index("ix_page_views_day", "day"),
        Index("ix_page_views_kind_day", "kind", "day"),
    )


class AppMeta(Base):
    """앱 내부 메타 (시드 버전 등 키-값 저장)"""
    __tablename__ = "app_meta"
    key = Column(String(50), primary_key=True)
    value = Column(String(200), nullable=False, default="")


class UseCase(Base):
    """용도 허브 — "어디에 쓰실 건가요?" 그리드에서 진입하는 페이지.

    tag_id가 있으면 추천 4종 아래에 해당 태그의 전체 폰트 목록이 이어 붙고,
    NULL이면 추천 4종만 노출된다. (신규 큐레이션 허브)
    """
    __tablename__ = "use_cases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(40), nullable=False, unique=True)
    title = Column(String(60), nullable=False)
    subtitle = Column(String(120), nullable=False, default="")
    # 연결된 모양/용도 태그 (없으면 순수 큐레이션 허브)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True)
    criteria = Column(Text, nullable=False, default="")   # 선정 기준
    howto = Column(Text, nullable=False, default="")      # 활용 방법 (구버전 한 문단 — tips 없을 때 폴백)
    # 활용 방법 3단 구조: [["크기·굵기", "1280×720 기준 ..."], ...]
    # 라벨을 고정 컬럼 3개로 두지 않은 이유: 허브마다 라벨이 다르다
    # (썸네일=글자 수 / 자막=위치 / 메뉴판=숫자 / 청첩장=행간).
    tips = Column(JSON, default=list)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    tag = relationship("Tag", lazy="joined")
    fonts = relationship(
        "UseCaseFont",
        back_populates="use_case",
        cascade="all, delete-orphan",
        order_by="UseCaseFont.rank",
        lazy="selectin",
    )
    phrases = relationship(
        "UseCasePhrase",
        back_populates="use_case",
        cascade="all, delete-orphan",
        order_by="UseCasePhrase.sort_order",
        lazy="selectin",
    )


class UseCaseFont(Base):
    """용도 허브의 상단 추천 폰트 (rank 순).

    font_id로 연결한다 — 이름 매칭은 어드민에서 폰트명을 바꾸는 순간
    조용히 끊어지기 때문이다.
    """
    __tablename__ = "use_case_fonts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    use_case_id = Column(Integer, ForeignKey("use_cases.id", ondelete="CASCADE"), nullable=False)
    font_id = Column(Integer, ForeignKey("fonts.id", ondelete="CASCADE"), nullable=False)
    rank = Column(Integer, nullable=False, default=0)
    reason = Column(Text, nullable=False, default="")

    use_case = relationship("UseCase", back_populates="fonts")
    font = relationship("Font", lazy="joined")

    __table_args__ = (
        Index("idx_ucf_use_case", "use_case_id"),
        Index("idx_ucf_font", "font_id"),
    )


class UseCasePhrase(Base):
    """용도 허브의 샘플 문구 칩 — 미리보기에 바로 넣어볼 문장."""
    __tablename__ = "use_case_phrases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    use_case_id = Column(Integer, ForeignKey("use_cases.id", ondelete="CASCADE"), nullable=False)
    text = Column(String(100), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)

    use_case = relationship("UseCase", back_populates="phrases")

    __table_args__ = (
        Index("idx_ucp_use_case", "use_case_id"),
    )


class GifTemplate(Base):
    """GIF 생성기 템플릿.

    사용자는 이 템플릿을 고르고 문구·폰트·효과만 바꿔 GIF를 받는다.
    렌더링·인코딩은 전부 브라우저에서 일어나므로 서버는 이 정의만 서빙한다.

    JSON 한 덩어리로 두지 않고 일부를 컬럼으로 뽑은 이유
    -------------------------------------------------
    - font_id: 폰트를 지웠을 때 깨지는 템플릿을 찾으려면 실제 컬럼이어야 한다.
      JSON 안에 두면 전 행을 파이썬에서 역직렬화해야 한다. ondelete는 SET NULL —
      폰트가 사라졌다고 조용히 템플릿까지 지우면 안 되고, 어드민이 보고 고쳐야 한다.
    - hub_slug / anim_category / ratio / gif_rating: 갤러리 필터가 쓰는 값이라
      DB에서 걸러야 한다.

    나머지(길이·fps·등장시간·매트·하이라이트·사진 위치)는 config에 둔다.
    제작툴의 snapshot() 출력과 같은 모양이다.
    """
    __tablename__ = "gif_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 화면에 보이는 번호이자 가져오기(import) 시 중복 판단 기준. '001' 같은 문자열.
    number = Column(String(8), nullable=False, unique=True)
    title = Column(String(80), nullable=False, default="")

    # 용도 허브 slug (use_cases.slug). FK로 묶지 않는 이유는 허브 시드가
    # 버전이 오르면 통째로 지웠다 다시 넣기 때문 — 그때 템플릿이 끌려가면 안 된다.
    hub_slug = Column(String(30), nullable=False, default="")

    anim = Column(String(30), nullable=False, default="typewriter")
    anim_category = Column(String(20), nullable=False, default="basic")  # basic|extended|cinematic|dynamic
    effect = Column(String(30), nullable=False, default="none")
    ratio = Column(String(10), nullable=False, default="16:9")
    gif_rating = Column(Integer, nullable=False, default=2, server_default="2")

    font_id = Column(Integer, ForeignKey("fonts.id", ondelete="SET NULL"), nullable=True)
    font_weight = Column(Integer, nullable=False, default=700, server_default="700")
    sample_text = Column(String(100), nullable=False, default="")

    config = Column(JSON, default=dict)

    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    font = relationship("Font", lazy="joined")

    __table_args__ = (
        Index("idx_gif_tpl_sort", "sort_order"),
        Index("idx_gif_tpl_hub", "hub_slug"),
    )


class GifUseCase(Base):
    """GIF 생성기의 용도 — 편집기에서 폰트를 고를 때 묶어 보여주는 단위.

    사이트의 use_cases(용도 허브)를 그대로 빌려 쓰지 않는 이유
    -------------------------------------------------------
    ① 분류 축이 다르다. /use/{slug}는 "이 용도에 어울리는 폰트를 고르는" 곳이고
       여기는 "움직이는 문구를 만드는" 곳이라, 청첩장처럼 GIF로 만들 일이 없는
       용도가 섞이고 반대로 인사·감성처럼 필요한 축이 없다.
    ② use_cases는 시드 버전이 오르면 통째로 지웠다 다시 넣는다. 거기에 얹어두면
       운영자가 GIF 쪽에서 폰트를 빼고 더한 손질이 배포 한 번에 사라진다.
    """
    __tablename__ = "gif_use_cases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(30), nullable=False, unique=True)
    title = Column(String(40), nullable=False)
    subtitle = Column(String(120), nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    fonts = relationship(
        "GifUseCaseFont",
        back_populates="use_case",
        cascade="all, delete-orphan",
        order_by="GifUseCaseFont.rank",
        lazy="selectin",
    )


class GifUseCaseFont(Base):
    """용도에 넣어둔 폰트 (rank 순). 어드민에서 추가·삭제한다.

    ondelete는 CASCADE — 폰트를 지우면 이 줄도 같이 사라지는 게 맞다.
    템플릿(SET NULL)과 다른 이유: 템플릿은 폰트를 잃어도 고쳐 쓸 대상이
    남지만, 여기는 목록의 한 줄일 뿐이라 남겨두면 빈 항목이 된다.
    """
    __tablename__ = "gif_use_case_fonts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    gif_use_case_id = Column(
        Integer, ForeignKey("gif_use_cases.id", ondelete="CASCADE"), nullable=False)
    font_id = Column(Integer, ForeignKey("fonts.id", ondelete="CASCADE"), nullable=False)
    rank = Column(Integer, nullable=False, default=0)

    use_case = relationship("GifUseCase", back_populates="fonts")
    font = relationship("Font", lazy="joined")

    __table_args__ = (
        Index("idx_gucf_use_case", "gif_use_case_id"),
        Index("idx_gucf_font", "font_id"),
        UniqueConstraint("gif_use_case_id", "font_id", name="uq_gucf_case_font"),
    )
