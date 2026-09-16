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

## 6. 도메인 연결 — MCP 가 한다 (직접 nginx 를 건드리지 않는다)

1. `set_routes` — `/` 를 8000 포트로 직결
2. `connect_domain` — DNS 확인 → certbot SSL → nginx 반영
3. `switch_mode app` — 도메인이 PHP 가 아니라 앱을 보게

> `connect_domain` 은 **도메인 A레코드가 서버 공인IP(210.207.108.175)를
> 미리 가리켜야** SSL 이 발급된다. 그래서 운영 도메인 연결은 Phase 4(전환)
> 에서 하고, 그 전까지는 에그호스팅 임시 주소로 검증한다.

## 7. 앞단 확인 ★ 이 셋은 띄운 직후에 본다

에그호스팅 nginx 가 어떻게 설정돼 있는지는 문서에 없다. 실제 응답으로 본다.

| 확인 | 왜 |
|---|---|
| `X-Forwarded-Proto` 가 `https` 로 오는가 | `http` 면 앱이 https 로 돌려보내고 그게 또 http 로 들어와 **무한 리다이렉트** |
| `Host` 가 원래 주소로 오는가 | 아니면 www→루트 정리와 옛 주소 301 이 죽는다 |
| 응답에 `Content-Encoding: gzip` 이 있는가 | 없으면 트래픽이 4배 (홈 62KB vs 15KB) |
| 50MB ZIP 업로드가 되는가 | `client_max_body_size` 가 작으면 어드민 업로드가 413 |

안 되는 항목이 있으면 `nginx-freefontpick.conf` 의 해당 부분을 근거로
에그호스팅에 요청한다.

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
