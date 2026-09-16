# 폰트픽 서버 설치 순서

에그호스팅 클라우드 서버에 올리는 절차.

**Phase 2 는 전부 에그호스팅 임시 주소에서 한다** — 그동안 freefontpick.co.kr 은
카페24에서 그대로 서비스되므로 여기서 뭘 하든 운영에 영향이 없다.

## 서버 (2026-09-16 확인)

| | |
|---|---|
| 접속 | `ssh ubuntu@210.207.108.175` |
| OS | Ubuntu 24.04.5 LTS (noble) |
| 사양 | 1코어 / 2GB / 디스크 약 48GB |
| Docker | **이미 설치돼 있음** (공식 Docker CE) |
| nginx | 설치돼 있고 설정은 비어 있음 — 에그호스팅 MCP 가 관리한다 |

**nginx 설정을 직접 쓰지 않는다.** `connect_domain`(SSL 발급+nginx 반영)과
`set_routes`(경로→포트 라우팅)를 에그호스팅 MCP 가 대신 해 준다.
같은 폴더의 `nginx-freefontpick.conf` 는 **쓰지 않는 참고본**이다 —
그쪽 nginx 가 헤더를 제대로 안 넘길 때 무엇을 고쳐 달라고 할지의 기준.

---

## 1. 기본 확인

```
sudo apt update
sudo apt install -y git

docker --version          # 이미 깔려 있다
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

마지막 줄 뒤에는 **로그아웃 후 다시 접속**해야 `docker` 를 sudo 없이 쓸 수 있다.

## 2. 코드 받기

```
sudo mkdir -p /srv/freefontpick
sudo chown $USER:$USER /srv/freefontpick
cd /srv/freefontpick
git clone https://github.com/magumini-stack/freefontpick.git app
```

## 3. user_data 복원 ★ 빠뜨리면 안 되는 단계

어드민이 올린 폰트·ZIP·제보 이미지와 **DB 본체**가 여기 들어 있다.
안 넣으면 사이트는 뜨지만 내용이 텅 빈다.

카페24 백업(`freefontpick-freefontpick_20260916_143625.tar.gz`, 732MB)을
서버에 올린 뒤:

```
cd /srv/freefontpick
tar -xzf freefontpick-freefontpick_*.tar.gz data/user_data
mv data/user_data ./user_data
rmdir data

# 컨테이너의 app 사용자(UID 1000)가 쓸 수 있어야 한다
sudo chown -R 1000:1000 /srv/freefontpick/user_data
```

들어 있어야 하는 것 — `du -sh /srv/freefontpick/user_data/*` 로 대조한다:

| 폴더 | 개수 | 용량 |
|---|---|---|
| fontzips | 79 | 359.9 MB |
| fonts | 289 | 94.5 MB |
| og_cache | 776 | 52.1 MB |
| samples | 174 | 41.9 MB |
| font_subsets | 603 | 39.4 MB |
| submission_images | 37 | 19.8 MB |
| freefontpick.db | 1 | 2.4 MB |
| piece_cache | 10 | 0.05 MB |

## 4. 환경변수

```
cd /srv/freefontpick/app
cp deploy/env.example .env
nano .env
```

`WEBFONT_CSS_KEY` 는 카페24에서 쓰던 값 그대로,
`SESSION_SECRET` 은 새로 만든 값을 넣는다:

```
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 5. 띄우고 확인 (아직 바깥에 안 보임)

```
cd /srv/freefontpick/app
docker compose up -d --build

docker compose ps          # healthy 가 될 때까지
docker compose logs --tail 40   # [db] SQLite 사용: ... 이 보여야 한다
```

서버 안에서만 확인:

```
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/robots.txt
```

DB 가 제대로 붙었는지 — **239 가 나와야 한다**:

```
docker compose exec app python -c "import sqlite3;print(sqlite3.connect('/app/user_data/freefontpick.db').execute('select count(*) from fonts').fetchone()[0])"
```

## 6. 도메인 연결 — 콘솔에서 한다

**⚠ A 레코드는 `210.207.108.175` 다.**

MCP 의 `connect_domain` 응답에는 `guideIp: 210.207.108.131` 이 들어 있는데
**이 값은 틀렸다.** 콘솔의 [도메인 연결] 안내가 맞다. `.131` 로 걸면
공용 엣지의 기본 vhost 로 떨어져 **다른 고객 사이트(abuse.animals.or.kr)가
뜬다** — 2026-09-16 에 실제로 겪었다.

확인하는 법:

```
openssl s_client -connect <도메인>:443 -servername <도메인> </dev/null 2>/dev/null   | openssl x509 -noout -subject
```

`CN=<우리 도메인>` 이 나와야 한다. 다른 이름이 나오면 A 레코드를 의심한다.

절차:

1. DNS 에 A 레코드 → `210.207.108.175`
   (루트 도메인은 `@` 와 `www` 두 개, 서브도메인은 그 라벨 하나)
2. 콘솔 [도메인 연결] 에 입력 후 **연결 신청** — DNS 확인·SSL 발급이 자동
3. 콘솔 [라우팅 설정] 에 `경로 /` → `포트 8000` 이 있는지 확인
   (MCP `set_routes` 로 넣은 것이 여기 보인다)

`switch_mode app` 은 쓰지 않는다 — "배포된 앱이 없다"며 거부된다.
에그호스팅 배포 체계로 올린 앱에만 적용되는 기능이고, 우리는 포트 직결이다.

### ⚠ 브라우저가 옛 IP 를 붙들고 있는다

A 레코드를 바꾼 뒤에는 **모든 리졸버가 새 IP 를 보는데도 크롬만 옛 주소로
가는** 일이 생긴다. 크롬이 자체 DNS 캐시와 **살아 있는 소켓**을 재사용하기
때문이다. 사이트가 바뀌지 않으면 서버를 의심하기 전에 이것부터 한다.

- `chrome://net-internals/#dns` → Clear host cache
- `chrome://net-internals/#sockets` → **Flush socket pools** ← 이게 핵심
- 그래도 안 되면 크롬 완전 종료 후 재실행

서버가 맞는지는 브라우저 말고 위의 `openssl` 한 줄로 판단한다.

## 7. 앞단 확인 (2026-09-16 실측)

| 확인 | 결과 |
|---|---|
| HTTPS · 인증서 | 정상 (Let's Encrypt, 자동 발급) |
| http → https | 301 |
| 리다이렉트 루프 | 없음 |
| `Host` 전달 | 정상 |
| **gzip** | **`text/html` 만 압축된다** ⚠ |

**JSON·JS·CSS·XML 이 비압축으로 나간다.** 엣지 nginx 에 `gzip_types` 가
설정돼 있지 않다. 에그호스팅에 요청해 둘 것. 답이 늦으면 앱에서
직접 압축한다(단, ZIP·woff2 까지 압축하지 않도록 타입을 걸러야 한다).

```
/            text/html                227,596 B → gzip
/api/fonts   application/json         231,388 B → 없음   (카페24에서는 35,752 B)
/sitemap.xml application/xml           83,334 B → 없음
*.js         application/javascript    22,240 B → 없음
*.css        text/css                  13,625 B → 없음
```

콘솔 [사이트 상태] 가 `정상 · 405` 로 뜬다. 헬스체크가 쓰는 메서드를
앱이 안 받아서인데, 판정은 정상이라 당장 문제는 없다.

## 8. 검증 (전부 통과해야 전환)

- [ ] 홈 — 폰트 카드가 뜨고 미리보기 글자가 **실제 폰트**로 보이는가
- [ ] 폰트 상세 — 웹폰트·라이선스·매거진 링크
- [ ] **ZIP 다운로드** — 어드민 업로드분과 번들분 **둘 다**
- [ ] GIF 생성 — 진입 팝업 → 저장 전 팝업 → 저장
- [ ] 폰트 조합찾기 — 캔버스 + 왼쪽 배너
- [ ] 매거진 8편 — 그림 전부
- [ ] OG 이미지 — 새로 그려지는가 (Pillow 동작)
- [ ] 제보 이미지 — 기존 것이 보이는가
- [ ] robots.txt / sitemap.xml / **ads.txt 는 404 여야 정상**
- [ ] 어드민 로그인, **재시작 후에도 로그인 유지** (SESSION_SECRET 확인)
- [ ] `docker stats` — 안정 상태 메모리

---

## 재배포 (코드를 고친 뒤)

```
cd /srv/freefontpick/app
git pull
docker compose up -d --build
```

`user_data` 는 마운트라 재배포와 무관하게 남는다.

## 되돌리기

- **컨테이너 문제** — `docker compose down` 후 직전 이미지로
- **전환 후 문제** — DNS A 레코드를 카페24(222.122.39.91)로 되돌린다.
  TTL 을 300초로 낮춰 두었으면 5분이면 복구된다.
  그래서 **카페24는 전환 후 2주간 끄지 않는다.**
