#!/bin/sh
# 폰트 찾기 엔진 업데이트(2026-10-22) — 새 코드로 다시 짓고, 폰트 목록을 새로 만들어(폰트픽에 새로 등록한 폰트·RakFont 등)
# 새 굵기의 글자 묶음을 구운 뒤 엔진을 다시 띄운다. 서버에서 저장소를 받은 뒤 한 줄:
#
#     cd /srv/freefontpick/app && git pull && sh deploy/finder_update.sh ;
#
# - 있던 굵기는 그대로 두고 새 굵기만 계산한다(굵기 키 방식 k1). 새 굵기 수에 따라 30분~1시간 남짓.
# - 굽는 동안에도 찾기는 옛 목록으로 그대로 돈다. 끝나면 뒤에서 기다리던 일이 엔진을 다시 띄운다
#   (다시 뜬 뒤 몇 분은 새 굵기의 느낌·새 눈 기준을 뒤에서 만든다).
# - 진행: /srv/freefontpick/finder_data/stacks.log (끝에 '묶음 끝'), 다시 띄운 시각: 같은 폴더 update.log
# - 이미 굽는 중이면 아무것도 하지 않는다 — 웹 터미널에서 붙여넣기가 두 번 들어가도 한 번만 돈다.
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=/srv/freefontpick/finder_data
if docker ps --format '{{.Names}}' | grep -qx ffp-bake; then
  echo "이미 굽는 중입니다. 진행: tail -n 2 $LOG/stacks.log"
  exit 0
fi
docker compose up -d --build || exit 1
docker compose run -d --rm --name ffp-bake finder sh -c "nice -n 19 python -u build_catalog.py --stacks 2350 > /data/stacks.log 2>&1" || exit 1
nohup sh -c '
  sleep 30
  while docker ps --format "{{.Names}}" | grep -qx ffp-bake; do sleep 30; done
  docker compose restart finder && echo "$(date "+%m-%d %H:%M") 굽기 끝, 엔진 다시 띄움"
' >> "$LOG/update.log" 2>&1 &
echo "굽기를 시작했습니다. 끝나면 엔진이 저절로 다시 뜹니다. 진행: tail -n 2 $LOG/stacks.log"
