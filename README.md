# FreeFontPick (폰트픽)

무료 한글 폰트 큐레이션 + 텍스트/GIF 디자인 서비스.
FastAPI 백엔드 하나가 API와 정적 사이트를 함께 서빙한다.

- 운영: https://freefontpick.co.kr (카페24 AI Space)
- 리포: `magumini-stack/freefontpick`

---

## 무엇을 하는 서비스인가

| 기능 | 설명 |
|---|---|
| 폰트 갤러리 | 무료 한글/영문 폰트를 카테고리(모양)별로 모아 보여주고, 원하는 문구를 넣어 한 번에 비교 |
| 폰트 상세 | 폰트별 고유 페이지 — 굵기별 미리보기, 다운로드 링크, 어울리는 폰트 조합(페어링) |
| 텍스트 디자인 | 폰트에 외곽선·그림자·네온·그라데이션 등 효과를 얹어 투명배경 PNG로 저장 |
| GIF 디자인 | 움직이는 글자 GIF를 템플릿 기반으로 제작 |
| 용도 허브 | "유튜브 썸네일", "발표·보고서" 등 용도별 폰트 추천 페이지 |
| 폰트 찾기 | 이미지를 올려 폰트 이름을 묻고 답하는 게시판 |
| 어드민 | 폰트/카테고리/페어링/공지/템플릿/용도 허브를 브라우저에서 직접 관리 |

SEO가 설계의 큰 축이다. 콘텐츠는 SPA가 클라이언트에서 그리지만,
`<head>`의 title/description/canonical/OG/JSON-LD는 **서버가 페이지별로 치환**해서
내려주고, JS를 렌더링하지 않는 크롤러를 위해 `<noscript>` 블록도 함께 심는다.

---

## 스택

- **Python 3.11** / FastAPI + SQLAlchemy 2.x
- **DB**: MySQL(카페24 자동 주입) ↔ SQLite fallback — 아래 "DB 선택 규칙" 참고
- **인증**: 세션 쿠키(itsdangerous) + bcrypt, 첫 로그인 시 비밀번호 변경 강제
- **이미지**: Pillow (OG 이미지 서버 렌더링), fontTools (OG 렌더링용 서브셋)
- **프론트**: 순수 HTML/JS (빌드 도구 없음). `static/` 아래 정적 파일

---

## 폴더 구조

```
freefontpick/
├── main.py                 # 카페24 ASGI 진입점 (app.main:app 재노출)
├── Procfile                # web: uvicorn app.main:app ...
├── runtime.txt             # python-3.11
├── requirements.txt
├── seed_data.json          # 폰트/카테고리 시드 (초기 142종)
├── fonts/                  # 배포에 묶인 woff2 시드 폰트 (읽기 전용 fallback)
├── fontfiles/              # 보조 폰트 파일
├── static/                 # 정적 사이트 (아래 표 참고)
└── app/
    ├── main.py             # FastAPI 앱 — 미들웨어, 라우터 등록, catch-all 정적 서빙
    ├── database.py         # DB URL 결정 + 세션
    ├── models.py           # SQLAlchemy 모델
    ├── schemas.py          # Pydantic 스키마
    ├── auth.py             # 세션 인증 의존성
    ├── seed.py             # 테이블 생성 + 시드 + 마이그레이션
    ├── header.py           # 공용 헤더 HTML 주입 (헤더 단일 소스화)
    ├── font_metrics.py     # 폰트 메트릭 계산 (페어링 점수용)
    ├── webfont_check.py    # 외부 웹폰트(CDN) 유효성 점검
    ├── pairing_data.py     # 페어링 시드 데이터
    ├── pairing_phrases.py  # 페어링 예시 문구
    ├── use_case_data.py    # 용도 허브 시드
    ├── gif_use_case_data.py / gif_template_data.py   # GIF 시드
    └── routers/            # API·페이지 라우터 (아래 표)
```

### static/ 주요 파일

| 파일 | 역할 |
|---|---|
| `index.html` | 홈 (갤러리 · 용도별 추천 · 폰트 찾기 탭) |
| `font.html` | 폰트 상세 + 텍스트 디자인 모달 템플릿 (`{{FFP_*}}` 마커를 서버가 치환) |
| `use.html` | 용도 허브 템플릿 (`{{UC_*}}` 마커) |
| `wisefont.html` | 와이즈폰트 배포 페이지 템플릿 |
| `gif.html` / `gif-templates.html` | GIF 에디터 / 템플릿 갤러리 |
| `admin.html` / `admin-gif.html` | 어드민 |
| `api-client.js` | 프론트 공용 API 클라이언트 |
| `ffp-effects.js` | 텍스트 효과 렌더링 |
| `gif-render.js` / `gif-export.js` | GIF 합성·내보내기 |
| `header.css` | 공용 헤더 스타일 (루트 `/header.css`로도 서빙) |
| `about/faq/policy/privacy.html` | 정보 페이지 |

---

## 라우터

### 페이지 (SSR — 메타태그 치환)

| 경로 | 파일 | 비고 |
|---|---|---|
| `/`, `/index.html` | `routers/design.py` | 헤더 주입 + 전체 폰트 `<noscript>` 링크 삽입 |
| `/font/{id}` | `routers/design.py` | 폰트 상세. 없는 id는 `/`로 302 |
| `/font/{id}/design` | `routers/design.py` | 텍스트 디자인. canonical은 `/font/{id}`로 통일 |
| `/design/{id}` | `routers/design.py` | 구 URL → `/font/{id}/design` **301** |
| `/find-font` | `routers/design.py` | 폰트 찾기 게시판 |
| `/about.html`, `/faq.html` | `routers/design.py` | 헤더 주입 |
| `/use/{slug}` | `routers/use_case_route.py` | 용도 허브. 추천 폰트도 서버 렌더 |
| `/wisefont/{slug}` | `routers/wisefont.py` | 와이즈폰트 배포 페이지 |
| `/gif`, `/gif/templates`, `/admin/gif` | `routers/gif.py` | GIF 페이지 |
| `/sitemap.xml`, `/robots.txt`, `/ads.txt` | `routers/seo.py` | |
| 그 외 모든 경로 | `app/main.py` catch-all | `static/` 파일 서빙 (traversal 차단) |

> ⚠️ 페이지 라우터는 반드시 catch-all(`/{full_path:path}`)보다 **먼저** 등록해야 한다.
> 순서가 바뀌면 `/font/1` 같은 요청이 정적 서빙에 가로채여 404가 난다.

### API

| 그룹 | 대표 엔드포인트 | 인증 |
|---|---|---|
| `auth` | `POST /api/auth/login` · `logout` · `change-password`, `GET /api/auth/status` | — |
| `fonts` | `GET/POST /api/fonts`, `GET/PATCH/DELETE /api/fonts/{id}`, `POST /api/fonts/reorder`, `GET /api/fonts/webfont-audit`, `POST /api/fonts/webfont-check` | 쓰기는 관리자 |
| `files` | `GET/POST/DELETE /api/fonts/{id}/file`, `GET/POST /api/fonts/{id}/weights`, `DELETE .../weights/{weight}` | 쓰기는 관리자 |
| `tags` | `GET/POST /api/tags`, `PATCH/DELETE /api/tags/{id}`, `POST /api/tags/reorder` | 쓰기는 관리자 |
| `notices` | `GET/POST /api/notices`, `GET/PATCH/DELETE /api/notices/{id}` | 쓰기는 관리자 |
| `pairings` | `GET /api/pairings`, `GET /api/fonts/{id}/pairings`, `GET /api/pairings/themes`, `auto-generate` · `regenerate-all` · `purge-orphans`, `GET /api/debug/font-audit` | 쓰기는 관리자 |
| `likes` | `POST/DELETE /api/fonts/{id}/like` | 공개 |
| `submissions` | `GET/POST /api/submissions`, `GET/PATCH/DELETE /api/submissions/{id}`, `POST .../answers`, `GET .../image` | 일부 관리자 |
| `use-cases` | `GET /api/use-cases`, `GET /api/use-cases/{slug}` | 공개 |
| `use-cases-admin` | `GET/PATCH /api/admin/use-cases`, `PUT .../fonts` · `.../phrases`, `POST .../reorder` | 관리자 |
| `gif-templates` | `GET/POST /api/gif-templates`, `PATCH/DELETE /api/gif-templates/{id}`, `POST /api/gif-templates/import`, `GET /api/gif-fonts`, `/api/gif-use-cases` CRUD | 쓰기는 관리자 |
| `preview-phrases` | `GET/POST /api/preview-phrases`, `PATCH/DELETE /{id}`, `POST /reorder` | 쓰기는 관리자 |
| `og-image` | `GET /api/fonts/{id}/og-image.png`, `GET /api/use-cases/{slug}/og-image.png`, `POST /api/fonts/og-warm` | 공개 |
| `sample-image` | `GET/POST/DELETE /api/fonts/{id}/sample-image` | 쓰기는 관리자 |
| `db-migrate` | `GET /api/admin/db-compare`, `POST /api/admin/db-migrate` | 관리자 + `MIGRATE_TOKEN` |
| — | `GET /api/health` — DB 종류·폰트/태그/관리자 수까지 노출 | 공개 |

전체 목록은 서버를 띄운 뒤 `/docs` 또는 `/openapi.json`에서 확인.

---

## 데이터 모델

`fonts` · `tags` · `font_tags`(다대다) · `font_weights` · `font_pairings` ·
`notices` · `admin_users` · `preview_phrases` · `app_meta` ·
`font_submissions` · `submission_answers` ·
`use_cases` · `use_case_fonts` · `use_case_phrases` ·
`gif_templates` · `gif_use_cases` · `gif_use_case_fonts`

`app_meta`는 시드 버전과 "어드민이 편집한 적 있음" 플래그를 담는다.
**이 플래그가 켜져 있으면 해당 영역의 시드를 덮어쓰지 않는다** — 배포할 때마다
어드민에서 손본 데이터가 날아가는 사고를 막기 위한 장치다.

---

## DB 선택 규칙 (`app/database.py`)

1. `DB_HOST`/`DB_USER`/`DB_PASSWORD`/`DB_NAME`이 모두 있으면 → **MySQL**
2. 단, `FORCE_SQLITE=1`이면 MySQL 환경변수를 무시하고 → **SQLite**
3. 아무것도 없으면 → **SQLite** (`LOCAL_DB_PATH` 또는 `/app/user_data/freefontpick.db`)

> 2026-08, 카페24가 이 프로젝트에 MySQL을 자동 주입하기 시작하면서 앱이 빈 MySQL로
> 갈아타 SQLite에 쌓아둔 운영 데이터가 통째로 안 보이는 사고가 났다. 플랫폼이 주입하는
> 자격증명은 지울 수 없어서 `FORCE_SQLITE` 스위치를 뒀다.
> **MySQL 이관이 끝나기 전까지 운영 환경은 `FORCE_SQLITE=1`을 유지한다.**
> 이관 도구는 `POST /api/admin/db-migrate` (`routers/db_migrate.py`).

시작 시 `[db] SQLite 사용: ...` / `[db] MySQL 사용: ...` 로그로 어느 쪽을 잡았는지 확인할 것.

---

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DB_HOST` `DB_PORT` `DB_NAME` `DB_USER` `DB_PASSWORD` | — | 카페24가 자동 주입 |
| `FORCE_SQLITE` | off | 켜면 MySQL 무시하고 SQLite 사용 |
| `LOCAL_DB_PATH` | `/app/user_data/freefontpick.db` | SQLite 파일 경로 (**로컬 개발 시 필수**) |
| `SESSION_SECRET` | 매 기동 랜덤 | 세션 쿠키 서명키. 미설정 시 재시작마다 로그인 세션 전부 끊김 |
| `SITE_URL` | `https://freefontpick.co.kr` | sitemap/robots에 쓰는 절대 URL |
| `FONTS_DIR` | `/app/user_data/fonts` | 업로드된 폰트 저장 경로 |
| `SAMPLES_DIR` | `/app/user_data/samples` | 상세페이지 샘플 이미지 |
| `SUBMISSION_IMAGES_DIR` | `/app/user_data/submission_images` | 폰트 찾기 첨부 이미지 |
| `OGIMAGE_CACHE_DIR` | `/app/user_data/og_cache` | OG 이미지 디스크 캐시 |
| `ADMIN_USERNAME` | `admin` | 초기 관리자 ID |
| `ADMIN_INITIAL_PASSWORD` | `freefontpick2026!` | 초기 비밀번호 (첫 로그인 시 변경 강제) |
| `MIGRATE_TOKEN` | — | DB 이관 API 보호용 토큰 |
| `MIGRATE_SQLITE_PATH` | `/app/user_data/freefontpick.db` | 이관 원본 SQLite 경로 |

> 카페24는 `/app/user_data/`만 재배포 후에도 보존한다. 영구 데이터는 전부 이 아래에 둔다.

---

## 로컬 개발

Windows 기준. `.claude/launch.json`이 `.venv\Scripts\python.exe`를 쓰도록 잡혀 있다.

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

기본값대로 두면 SQLite가 `/app/user_data/`(윈도우에서는 `C:\app\user_data\`)에 생기므로,
프로젝트 안에 두려면 `LOCAL_DB_PATH`를 지정한다.

```bash
set LOCAL_DB_PATH=.\local.db
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload
```

- 사이트: http://localhost:8000
- 어드민: http://localhost:8000/admin.html (`admin` / `freefontpick2026!`)
- API 문서: http://localhost:8000/docs
- 상태 점검: http://localhost:8000/api/health

첫 기동 시 `init_db()`가 테이블 생성 + 시드 + 마이그레이션을 수행한다.
로컬 시드는 폰트 142종이고, 페어링·용도 허브·GIF 템플릿 시드는 그보다 나중에
어드민에서 추가된 폰트(id 143~)를 참조하므로 **`⚠ ... 폰트 미발견` 경고가 정상적으로 뜬다.**
운영 DB에는 그 폰트들이 있어 경고가 나지 않는다.

---

## 캐시 관련 장치 두 가지

카페24 앞단 프록시 설정을 바꿀 수 없어서 앱에서 우회한 것들이다. 지우지 말 것.

1. **`/api/*` 응답 no-store** (`app/main.py`)
   커스텀 도메인 앞단이 API GET 응답을 캐시해서, 어드민에서 고쳐도 방문자에게 옛
   데이터가 나갔다. 단 `/file`, `/og-image.png`, `/sample-image`는 캐시가 이득이라 제외.

2. **정적 JS/CSS URL 버전 스탬프** (`app/main.py`)
   앞단이 `/static/*`에 10년 캐시를 붙여서, 배포로 JS를 고쳐도 브라우저가 옛 파일을
   계속 썼다. HTML을 내보낼 때 `src`/`href`를 `?v={내용 md5 8자리}`로 바꿔 캐시를 비켜간다.
   수정시각이 아니라 **내용**으로 해시하므로 git 배포로 mtime이 전부 바뀌어도
   실제로 안 바뀐 파일은 재다운로드되지 않는다.

---

## 배포 (카페24 AI Space)

```bash
git add -A
git commit -m "변경 내용"
git push origin main
```

카페24에서 재배포하면 `requirements.txt` + `app/main.py`를 보고 python 런타임으로
자동 감지한다. 실행 커맨드는 `Procfile`을 따른다.

배포 후 확인 순서:

1. `/api/health` — `db_type`이 의도한 값인지, `fonts` 카운트가 이전과 같은지
2. 시작 로그의 `[db] ... 사용:` 줄
3. 어드민 로그인 → 폰트 목록이 보이는지

---

## 폰트 파일 정책

**서버는 폰트를 변환하지 않는다.** 2026-07에 서버 측 서브셋/woff2 변환을 완전히
제거했다 — 대용량 폰트 변환 중 메모리가 폭주해 앱 전체가 내려간 사고 때문이다.
어드민이 **이미 woff2로 변환한 파일만** 올릴 수 있고, 서버는 검증 후 그대로 저장한다.
(OG 이미지 렌더링에서만 fontTools 서브셋을 쓴다 — 메모리에서 몇 글자만 다룬다.)

`GET /api/fonts/{id}/weights`는 세 소스를 우선순위대로 병합한다:
DB `font_weights`(어드민 개별 업로드) → 매니페스트 기반 해석 → 대표 파일.
외부 웹폰트(`webfont_css_url`)가 있으면 `webfont` 소스로도 노출된다.
