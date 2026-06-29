# FreeFontPick — 백엔드 통합 배포 패키지

이 ZIP은 기존 정적 사이트를 **FastAPI 백엔드 + 정적 사이트 통합**으로 교체하는 배포 패키지입니다.

## 변경점

- **백엔드 추가**: Python FastAPI + MySQL + 자동 폰트 서브셋 변환
- **관리자 인증**: 세션 기반 + 첫 로그인 시 비밀번호 변경 강제
- **운영 데이터 일원화**: 어드민에서 변경한 폰트/카테고리/공지가 모든 방문자에게 즉시 반영
- **폰트 파일 서빙**: `/fonts/*.woff2` → `/api/fonts/{id}/file`

## 배포 절차

### 1. GitHub 리포에 코드 교체

기존 `magumini-stack/freefontpick` 리포의 모든 파일을 이 ZIP의 내용으로 **교체**합니다.

```bash
git clone https://github.com/magumini-stack/freefontpick.git
cd freefontpick
# 기존 파일 모두 삭제 (.git 폴더는 유지)
find . -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
# ZIP 압축 풀어서 모든 파일을 이 폴더에 복사
git add -A
git commit -m "Migrate to FastAPI backend"
git push origin main
```

또는 GitHub Desktop:
1. 로컬 freefontpick 폴더에서 기존 파일 전부 삭제 (.git 폴더는 남겨두기)
2. ZIP 풀어서 모든 파일/폴더를 그 폴더에 붙여넣기
3. GitHub Desktop에서 변경사항 확인 → Commit → Push

### 2. 카페24에서 재배포 (force)

기존 정적 사이트가 있는 공간(space_id=1123)에 **force=true** 옵션으로 재배포:
- 런타임: **python**으로 자동 감지됨 (`requirements.txt` + `app/main.py` 존재)
- DB: MySQL 자동 생성 + 환경변수 자동 주입
- 영구 데이터: `/app/user_data/` (폰트 파일 자동 보존)

### 3. 초기 관리자 계정으로 로그인

배포 완료 후:
- URL: `https://freefontpick-freefontpick.mycafe24.ai/admin.html`
- ID: `admin`
- 초기 비밀번호: `freefontpick2026!`
- **첫 로그인 시 비밀번호 변경이 강제됩니다**

### 4. 환경변수 (선택)

카페24에서 추가로 설정 권장:
- `SESSION_SECRET`: 세션 쿠키 서명용 강력한 무작위 문자열
  (설정 안 하면 매 재시작마다 새로 생성되어 모든 세션이 끊김)

## 폴더 구조

```
freefontpick/
├── app/                # FastAPI 백엔드
│   ├── main.py        # 앱 진입점
│   ├── database.py    # MySQL 연결
│   ├── models.py      # DB 모델
│   ├── schemas.py     # Pydantic 스키마
│   ├── auth.py        # 인증
│   ├── subset.py      # 폰트 서브셋 변환
│   ├── seed.py        # 초기 데이터 로드
│   └── routers/       # API 라우터
├── static/            # 정적 파일 (index.html, admin.html 등)
├── fonts/             # 시드 폰트 142개 (앱 시작 시 user_data/로 복사)
├── seed_data.json     # 142개 폰트 + 18개 카테고리 시드
├── requirements.txt
├── Procfile
├── runtime.txt
└── README.md (이 파일)
```

## API 명세 (요약)

| 경로 | 메서드 | 인증 | 설명 |
|------|-------|------|------|
| `/api/health` | GET | 공개 | 헬스체크 |
| `/api/fonts` | GET | 공개 | 폰트 목록 |
| `/api/fonts` | POST | 관리자 | 폰트 추가 |
| `/api/fonts/{id}` | PATCH/DELETE | 관리자 | 폰트 수정/삭제 |
| `/api/fonts/{id}/file` | GET | 공개 | 폰트 파일 |
| `/api/fonts/{id}/file` | POST | 관리자 | 파일 업로드 + 서브셋 변환 |
| `/api/tags` | GET/POST/PATCH/DELETE | 일부 관리자 | 카테고리 |
| `/api/notices` | GET/POST/PATCH/DELETE | 일부 관리자 | 공지사항 |
| `/api/auth/login` | POST | - | 로그인 |
| `/api/auth/change-password` | POST | 관리자 | 비밀번호 변경 |

## 로컬 개발

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
SQLite로 자동 fallback (DB 환경변수가 없으면).
