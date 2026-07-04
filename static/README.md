# 5가지 수정 사항

## 📁 push 위치

| 받으신 파일 | → GitHub 위치 |
|------------|-------------|
| `index.html` | `static/index.html` |
| `admin.html` | `static/admin.html` |

## 🎯 변경 사항

### 1. 폰픽 → 폰트픽
- 8곳 모두 치환 (title, meta description, keywords, OG, Twitter, hero title 등)

### 2. 광고 4곳 임시 비활성화 (AdSense 승인 대기)
- 갤러리 첫 번째 광고 (row-1): 렌더링 안 함
- 갤러리 두 번째 광고 (row-3): 렌더링 안 함
- 하단 플로팅 광고: 표시 안 함
- 다운로드 광고 모달: 건너뛰고 바로 다운로드 페이지로 이동

**AdSense 승인 후 복구 방법**: 각 광고 관련 코드에 주석 형태(`/* AdSense 승인 후 복구: ... */`)로 남겨두었으니, 승인 완료 후 주석을 풀면 즉시 광고가 노출됩니다.

### 3. 공지사항 날짜 안 나오는 오류 수정
- 원인: 백엔드는 `created_at` (snake_case)로 응답하는데 프론트는 `createdAt` (camelCase)를 참조
- 해결: `noticeCreatedAt(n)`, `noticeUpdatedAt(n)` 헬퍼 함수 추가하여 두 케이스 모두 대응
- `formatNoticeDate`도 유효하지 않은 날짜 처리 개선
- index.html + admin.html 둘 다 수정

### 4. hero-eyebrow 텍스트 변경
- "무료 상업용 폰트 큐레이션" → "상업용 무료폰트 큐레이션"

### 5. hero-sub 텍스트 변경
- "검색하고 클릭하면 바로 다운로드 — 모두 무료, 상업적 이용 가능"
- → "형태, 용도, 느낌, 분위기로 검색 하고 무료 다운로드"

## 🚀 push 후 확인

1. GitHub Desktop으로 2개 파일 덮어쓰기
2. Commit: `Rename 폰픽→폰트픽, disable ads pending approval, fix notice dates, update hero copy`
3. Push origin
4. 카페24 자동 재배포 (1~2분)
5. 강제 새로고침 (Ctrl+Shift+R)

## ✅ 확인 체크리스트

- [ ] 사이트 상단 및 메타에 "폰트픽"으로 표시
- [ ] 갤러리에 광고 카드 안 보임 (폰트 카드만 표시)
- [ ] 하단 플로팅 광고 안 보임
- [ ] 폰트 다운로드 클릭 시 광고 모달 없이 바로 새 창으로 이동
- [ ] 공지사항 목록/상세에 날짜(YYYY.MM.DD) 정상 표시
- [ ] hero 영역 "상업용 무료폰트 큐레이션" + "형태, 용도, 느낌, 분위기로 검색 하고 무료 다운로드"
