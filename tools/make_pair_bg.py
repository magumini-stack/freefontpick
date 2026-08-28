"""폰트 조합 찾기 캔버스 배경 — 원본 PNG 를 WebP 로 굽는다.

파일 이름을 목업 이름(thumb·card·namecard·poster·note·magazine)으로 맞춘다.
CSS 가 .mk-{이름} 에 배경을 걸기 때문이고, '뜻밖의 발견'은 다른 카테고리의
틀을 빌려 쓰므로 이렇게 두면 배경도 저절로 따라간다.

    python tools/make_pair_bg.py "<원본 폴더>"

원본이 바뀌면 다시 돌리고 결과물을 함께 커밋한다.
"""
import io
import os
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "pair-bg"

# 원본 파일 이름(사용자가 붙인 것) → 목업 이름
SRC = {
    "썸네일": "thumb",
    "SNS": "card",
    "브랜딩": "namecard",
    "포스터": "poster",
    "감성 손글씨": "note",
    "본문 읽기": "magazine",
}

# 캔버스는 최대 916px 폭이다. 2배 화면을 감안해 1600 이면 넉넉하고,
# 그 이상은 파일만 무거워진다.
WIDTH = 1600
QUALITY = 80


def main(src_dir: str):
    d = Path(src_dir)
    if not d.is_dir():
        raise SystemExit("원본 폴더가 없다: %s" % d)
    OUT.mkdir(parents=True, exist_ok=True)

    found = {}
    for p in d.iterdir():
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        found[p.stem.strip()] = p

    missing = [k for k in SRC if k not in found]
    if missing:
        raise SystemExit("원본을 못 찾았다: %s\n폴더에 있는 것: %s"
                         % (", ".join(missing), ", ".join(sorted(found))))

    total = 0
    for ko, name in SRC.items():
        im = Image.open(found[ko]).convert("RGB")
        if im.width != WIDTH:
            im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
        dst = OUT / (name + ".webp")
        im.save(dst, "WEBP", quality=QUALITY, method=6)
        kb = dst.stat().st_size / 1024
        total += kb
        print("  %-10s %-14s %dx%d  %6.0f KB  (원본 %.0f KB)"
              % (name, ko, im.width, im.height, kb,
                 found[ko].stat().st_size / 1024))
    print("\n합계 %.0f KB → %s" % (total, OUT))


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main(sys.argv[1] if len(sys.argv) > 1
         else os.path.expanduser("~/Desktop/폰트조합찾기 배경이미지"))
