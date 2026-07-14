"""폰트 찾기 게시판 API

- 로그인 없이 누구나 글쓰기 가능 (닉네임 자유 입력)
- 이미지를 올리면 다른 사람들이 어떤 폰트인지 답변해주는 용도
- 이미지 또는 설명 중 최소 하나는 필요, 이미지는 1장까지
- 질문 목록/상세는 공개, 질문 작성도 공개
- 답변도 로그인 없이 누구나 작성 가능 (SubmissionAnswer)
- 삭제(질문/답변 모두)는 관리자만
- 스팸 방지를 위한 가벼운 IP rate limit (질문/답변 각각 별도)
"""
import os
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import FontSubmission, SubmissionAnswer
from ..auth import require_password_changed
from ..schemas import SubmissionOut, SubmissionUpdate, AnswerOut

router = APIRouter(prefix="/api/submissions", tags=["submissions"])

# 영구 저장 경로 — 카페24 정책상 /app/user_data/만 보존
IMAGES_DIR = Path(os.getenv("SUBMISSION_IMAGES_DIR", "/app/user_data/submission_images"))
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8MB
ALLOWED_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

# 간단한 IP rate limit (스팸/도배 방지) — 같은 IP는 30초에 1개만 작성 가능
_RATE_LIMIT_SECONDS = 30
_last_post_at: dict[str, float] = {}
_last_answer_at: dict[str, float] = {}


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"


def _check_rate_limit(bucket: dict, ip: str):
    now = time.time()
    last = bucket.get(ip)
    if last and (now - last) < _RATE_LIMIT_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"너무 빠르게 작성하셨어요. {_RATE_LIMIT_SECONDS}초 후 다시 시도해주세요.",
        )
    bucket[ip] = now
    if len(bucket) > 5000:
        threshold = now - 3600
        for k, v in list(bucket.items()):
            if v < threshold:
                bucket.pop(k, None)


@router.get("", response_model=list[SubmissionOut])
def list_submissions(db: Session = Depends(get_db)):
    """전체 목록 — 최신순. 공개 API (제보자 본인도 자기 글 확인 가능)"""
    items = db.query(FontSubmission).order_by(FontSubmission.created_at.desc()).all()
    return items


@router.get("/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: int, db: Session = Depends(get_db)):
    item = db.query(FontSubmission).filter(FontSubmission.id == submission_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
    return item


@router.post("", response_model=SubmissionOut, status_code=status.HTTP_201_CREATED)
async def create_submission(
    request: Request,
    nickname: str = Form("익명"),
    content: str = Form(""),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    """폰트 찾기 글 작성 — 로그인 불필요.

    이미지 또는 설명 중 최소 하나는 있어야 함.
    (폰트 이름/링크는 더 이상 요구하지 않음 — 이 게시판은
    "이 이미지 속 폰트가 뭔가요?"를 묻는 용도이기 때문)
    """
    _check_rate_limit(_last_post_at, _client_ip(request))

    nickname = (nickname or "익명").strip()[:50] or "익명"
    content = (content or "").strip()[:2000]
    has_image = image is not None and bool(image.filename)

    if not content and not has_image:
        raise HTTPException(
            status_code=400,
            detail="이미지 또는 설명 중 하나는 알려주세요",
        )

    image_path = None
    if has_image:
        ext = Path(image.filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(
                status_code=400,
                detail="이미지는 jpg, png, gif, webp 형식만 가능해요",
            )
        data = await image.read()
        if len(data) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"이미지가 너무 커요 (최대 {MAX_IMAGE_SIZE // 1024 // 1024}MB)",
            )
        if not data:
            raise HTTPException(status_code=400, detail="이미지 파일이 비어있어요")
        filename = f"{uuid.uuid4().hex}{ext}"
        out_path = IMAGES_DIR / filename
        try:
            out_path.write_bytes(data)
            image_path = filename
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"이미지 저장 실패: {e}")

    item = FontSubmission(
        nickname=nickname,
        font_name="",  # 더 이상 사용하지 않음 (하위 호환을 위해 컬럼은 유지)
        content=content,
        link="",  # 더 이상 사용하지 않음
        image_path=image_path,
        status="pending",
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return item


@router.get("/{submission_id}/image")
def get_submission_image(submission_id: int, db: Session = Depends(get_db)):
    """제보 게시글의 첨부 이미지 서빙"""
    item = db.query(FontSubmission).filter(FontSubmission.id == submission_id).first()
    if not item or not item.image_path:
        raise HTTPException(status_code=404, detail="이미지가 없습니다")
    p = IMAGES_DIR / item.image_path
    if not p.exists():
        raise HTTPException(status_code=404, detail="이미지 파일을 찾을 수 없습니다")
    return FileResponse(
        path=p,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ═══════════════════════════════════════════════════════
# 답변 — 로그인 없이 누구나 작성. 관리자는 삭제만 가능.
# ═══════════════════════════════════════════════════════

@router.post("/{submission_id}/answers", response_model=AnswerOut, status_code=status.HTTP_201_CREATED)
async def create_answer(
    submission_id: int,
    request: Request,
    nickname: str = Form("익명"),
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    """질문에 답변 달기 — 로그인 불필요. 누구나 작성 가능."""
    item = db.query(FontSubmission).filter(FontSubmission.id == submission_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="질문을 찾을 수 없습니다")

    _check_rate_limit(_last_answer_at, _client_ip(request))

    nickname = (nickname or "익명").strip()[:50] or "익명"
    content = (content or "").strip()[:1000]
    if not content:
        raise HTTPException(status_code=400, detail="답변 내용을 입력해주세요")

    answer = SubmissionAnswer(submission_id=submission_id, nickname=nickname, content=content)
    db.add(answer)
    db.commit()
    db.refresh(answer)
    return answer


@router.delete("/answers/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_answer(
    answer_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    """관리자 전용 — 부적절한 답변 삭제"""
    answer = db.query(SubmissionAnswer).filter(SubmissionAnswer.id == answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="답변을 찾을 수 없습니다")
    db.delete(answer)
    db.commit()


@router.patch("/{submission_id}", response_model=SubmissionOut)
def update_submission(
    submission_id: int,
    payload: SubmissionUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    """관리자 전용 — 상태/답변 변경 (하위호환용, 더 이상 어드민 UI에서 사용 안 함)"""
    item = db.query(FontSubmission).filter(FontSubmission.id == submission_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in ("pending", "reviewed", "added"):
        raise HTTPException(status_code=400, detail="잘못된 상태값입니다")
    for k, v in data.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    """관리자 전용 — 게시글 + 첨부 이미지 + 답변 전체 삭제"""
    item = db.query(FontSubmission).filter(FontSubmission.id == submission_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다")
    if item.image_path:
        p = IMAGES_DIR / item.image_path
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    db.delete(item)  # cascade="all, delete-orphan" 로 answers도 함께 삭제됨
    db.commit()
