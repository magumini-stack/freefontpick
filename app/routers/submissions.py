"""무료폰트 제보 게시판 API

- 로그인 없이 누구나 글쓰기 가능 (닉네임 자유 입력)
- 이미지 1장 첨부 가능 (선택)
- 목록/상세는 공개, 삭제/상태변경은 관리자만
- 스팸 방지를 위한 가벼운 IP rate limit
"""
import os
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import FontSubmission
from ..auth import require_password_changed
from ..schemas import SubmissionOut, SubmissionUpdate

router = APIRouter(prefix="/api/submissions", tags=["submissions"])

# 영구 저장 경로 — 카페24 정책상 /app/user_data/만 보존
IMAGES_DIR = Path(os.getenv("SUBMISSION_IMAGES_DIR", "/app/user_data/submission_images"))
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8MB
ALLOWED_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

# 간단한 IP rate limit (스팸/도배 방지) — 같은 IP는 30초에 1개만 작성 가능
_RATE_LIMIT_SECONDS = 30
_last_post_at: dict[str, float] = {}


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
    font_name: str = Form(...),
    content: str = Form(""),
    link: str = Form(""),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    """제보 글 작성 — 로그인 불필요. 이미지는 선택."""
    # rate limit
    ip = _client_ip(request)
    now = time.time()
    last = _last_post_at.get(ip)
    if last and (now - last) < _RATE_LIMIT_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"너무 빠르게 작성하셨어요. {_RATE_LIMIT_SECONDS}초 후 다시 시도해주세요.",
        )

    nickname = (nickname or "익명").strip()[:50] or "익명"
    font_name = (font_name or "").strip()[:100]
    if not font_name:
        raise HTTPException(status_code=400, detail="폰트 이름을 입력해주세요")
    content = (content or "").strip()[:2000]
    link = (link or "").strip()[:500]

    image_path = None
    if image is not None and image.filename:
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
        font_name=font_name,
        content=content,
        link=link,
        image_path=image_path,
        status="pending",
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    _last_post_at[ip] = now
    # 메모리 보호 — 오래된 기록 정리
    if len(_last_post_at) > 5000:
        threshold = now - 3600
        for k, v in list(_last_post_at.items()):
            if v < threshold:
                _last_post_at.pop(k, None)

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


@router.patch("/{submission_id}", response_model=SubmissionOut)
def update_submission(
    submission_id: int,
    payload: SubmissionUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_password_changed),
):
    """관리자 전용 — 상태/답변 변경"""
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
    """관리자 전용 — 게시글 + 첨부 이미지 삭제"""
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
    db.delete(item)
    db.commit()
