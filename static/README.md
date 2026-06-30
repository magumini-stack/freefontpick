# 어드민 + 광고 업데이트 — 변경 파일

## 📁 push 위치

| 받으신 파일 | → GitHub 위치 |
|------------|-------------|
| `index.html` | `static/index.html` |
| `admin.html` | `static/admin.html` |
| `api-client.js` | `static/api-client.js` |

3개 파일 모두 `static/` 폴더에 덮어쓰기.

## 🎯 적용된 변경 사항

### 1. 폰트 업로드 후 미리보기 적용 문제 (안전망)
- `index.html`에 `getEffectiveStack(f)` 함수 추가
- `has_file=true`인데 stack에 `FFP-{id}` family가 없으면 자동으로 prepend
- 폰트 카드 미리보기 + TOP 10 모두 이 함수 사용
- 백엔드 수정과 함께 동작하여 신규 업로드 폰트가 즉시 미리보기에 적용됨

### 2. 카테고리 순서 변경 (신규)
- 카테고리 관리 탭에 "순서 변경" 버튼 추가
- 클릭 시 각 카테고리에 ↑↓⬆⬇ 4개 버튼 표시
  - ⬆ 맨 위로
  - ↑ 한 칸 위로
  - ↓ 한 칸 아래로
  - ⬇ 맨 아래로
- 변경 즉시 메인 페이지의 카테고리 필터 바에 반영됨

### 3. 폰트 순서 변경 (확인)
- 이미 존재. 폰트 관리 탭의 "순서 변경" 버튼으로 사용 가능
- 추천순(curator) 정렬에 반영됨

### 4. 애드센스 광고 slot 4개 교체
| 위치 | 새 slot ID |
|------|----------|
| 갤러리 첫 번째 (row-1) | 4304276310 |
| 갤러리 두 번째 (row-3) | 3185233399 |
| 하단 플로팅 | 1813844341 |
| 다운로드 모달 | 3355412338 |

### 5. api-client.js의 TagStore 확장
- `move(name, delta)` — 한 칸씩 이동
- `moveTo(name, idx)` — 특정 인덱스로 이동
- `setOrder(names[])` — 배열 순서대로 일괄 재정렬
- 백엔드 `PATCH /api/tags/{id}` 의 sort_order 기능 사용

## 🚀 push + 배포

1. GitHub Desktop으로 3개 파일을 `static/` 폴더에 덮어쓰기
2. Commit: `Add category reorder, font preview fix, new ad slots`
3. Push origin
4. 카페24 자동 재배포 대기 (1~2분)
5. 사이트 강제 새로고침 (`Ctrl+Shift+R`)

## ✅ 동작 확인 체크리스트

배포 완료 후:

- [ ] 어드민 → 폰트 관리 → 새 폰트 등록 + woff2 업로드 → 메인 페이지에서 폰트가 미리보기에 적용되는지
- [ ] 어드민 → 카테고리 관리 → "순서 변경" 버튼 → ↑↓ 버튼으로 카테고리 순서 바꾸기 → 메인 페이지의 카테고리 필터에 반영되는지
- [ ] 어드민 → 폰트 관리 → "순서 변경" 버튼 → 폰트 순서 바꾸기 → 메인 페이지에서 추천순 정렬 시 새 순서로 표시되는지
- [ ] AdSense 콘솔에서 4개 새 slot이 사이트에 게재되는지 (광고 활성화에는 시간 걸림)

## ⚠️ 백엔드는 이미 적용됨

다음 3개 백엔드 파일은 제가 이미 직접 commit해서 자동 재배포되었어요. 별도 작업 불필요:
- `app/database.py` — SQLite를 `/app/user_data/`에 저장 (데이터 영구 보존)
- `app/main.py` — 헬스체크에 DB 종류 노출
- `app/routers/files.py` — 폰트 업로드 시 stack 자동 갱신 + 시드 폰트 fallback
