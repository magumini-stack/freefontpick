# 폰트픽 서버 설치 순서

에그호스팅 클라우드 서버(Ubuntu)에 올리는 절차.
**Phase 2 는 전부 무료 서브도메인에서 한다** — 그동안 freefontpick.co.kr 은
카페24에서 그대로 서비스되므로 여기서 뭘 하든 운영에 영향이 없다.

---

## 1. 서버 기본

```
sudo apt update && sudo apt upgrade -y
sudo apt install -y nginx git

# 도커 공식 저장소 (우분투 기본 저장소의 docker.io 는 버전이 낮다)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# 여기서 한 번 로그아웃 후 다시 접속해야 docker 를 sudo 없이 쓸 수 있다

sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

**8000 번은 절대 열지 않는다.** 컨테이너가 127.0.0.1 에만 묶여 있어
바깥에서 닿을 수 없고, nginx 를 거쳐야만 들어온다.

## 2. 코드 받기

```
sudo mkdir -p /srv/freefontpick
sudo chown $USER:$USER /srv/freefontpick
cd /srv/freefontpick
git clone https://github.com/magumini-stack/freefontpick.git app
```

## 3. user_data 복원 ★ 빠뜨리면 안 되는 단계

어드민이 올린 폰트·ZIP·제보 이미지와 **DB 본체**가 여기 들어 있다.
이걸 안 넣으면 사이트는 뜨지만 내용이 텅 빈다.

```
cd /srv/freefontpick
# 카페24 백업 tar.gz 를 올려둔 뒤
tar -xzf freefontpick-freefontpick_*.tar.gz data/user_data
mv data/user_data ./user_data
rmdir data

# 컨테이너의 app 사용자(UID 1000)가 쓸 수 있어야 한다
sudo chown -R 1000:1000 /srv/freefontpick/user_data
```

들어 있어야 하는 것 — 개수가 맞는지 본다:

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

```
du -sh /srv/freefontpick/user_data/*   # 위 표와 대조
```

## 4. 환경변수

```
cd /srv/freefontpick/app
cp deploy/env.example .env
nano .env        # WEBFONT_CSS_KEY 와 SESSION_SECRET 을 채운다
```

## 5. 띄우고 확인 (아직 바깥에 안 보임)

```
cd /srv/freefontpick/app
docker compose up -d --build

docker compose ps          # healthy 가 될 때까지 기다린다
docker compose logs -f     # [db] SQLite 사용: ... 이 보여야 한다
```

서버 안에서만 확인:

```
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/robots.txt
curl -s http://127.0.0.1:8000/api/fonts | head -c 200
```

DB 가 제대로 붙었는지 — **239 가 나와야 한다**:

```
docker compose exec app python -c "import sqlite3;print(sqlite3.connect('/app/user_data/freefontpick.db').execute('select count(*) from fonts').fetchone()[0])"
```

## 6. nginx + 인증서

```
sudo cp deploy/nginx-freefontpick.conf /etc/nginx/sites-available/freefontpick
sudo nano /etc/nginx/sites-available/freefontpick   # YOUR_DOMAIN 5곳 치환
sudo ln -s /etc/nginx/sites-available/freefontpick /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t          # ★ 반드시 통과시킨 뒤에
sudo systemctl reload nginx
```

인증서 — 에그호스팅이 콘솔에서 발급해 주면 그쪽을 쓰고, 직접 받아야 하면:

```
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d <도메인>
```

> 인증서가 아직 없으면 nginx 가 443 블록에서 기동에 실패한다.
> 그럴 때는 443 블록을 잠시 주석 처리하고 80 만 살린 뒤 certbot 을 돌린다.

## 7. 검증 (전부 통과해야 전환)

- [ ] 홈 — 폰트 카드가 뜨고 미리보기 글자가 **실제 폰트**로 보이는가
- [ ] 폰트 상세 — 웹폰트·라이선스·매거진 링크
- [ ] **ZIP 다운로드** — 어드민 업로드분과 번들분 **둘 다**
- [ ] GIF 생성 — 진입 팝업 → 저장 전 팝업 → 저장
- [ ] 폰트 조합찾기 — 캔버스 + 왼쪽 배너
- [ ] 매거진 8편 — 그림 전부
- [ ] OG 이미지 — 새로 그려지는가 (Pillow 동작)
- [ ] 제보 이미지 — 기존 것이 보이는가
- [ ] robots.txt / sitemap.xml / **ads.txt 는 404 여야 정상**
- [ ] 어드민 로그인, 재시작 후에도 로그인 유지 (SESSION_SECRET 확인)
- [ ] `docker stats` — 안정 상태 메모리
- [ ] `curl -sI https://<도메인>/ | grep -i content-encoding` → **gzip** 이 보여야 한다

---

## 재배포 (코드를 고친 뒤)

```
cd /srv/freefontpick/app
git pull
docker compose up -d --build
```

`user_data` 는 마운트라 재배포와 무관하게 남는다.

## 되돌리기

- **컨테이너 문제** — `docker compose down` 후 이전 이미지로
- **전환 후 문제** — DNS A 레코드를 카페24(222.122.39.91)로 되돌린다.
  TTL 을 300초로 낮춰 두었으면 5분이면 복구된다.
  그래서 **카페24는 전환 후 2주간 끄지 않는다.**
