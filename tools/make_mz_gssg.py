"""매거진 「사진 위에 글씨」 글에 쓸 그림을 캐러셀에서 만든다.

원본은 인스타 캐러셀(1080×1350, 4:5) 9장이다. 그대로 쓰면 두 가지가 걸린다.

  1. 파일이 크다(장당 100~450KB PNG). 글 하나에 네 장이면 1MB 를 넘는다.
  2. 대표 그림(og:image)은 1.91:1 이 필요하다. 4:5 를 그대로 주면 카톡·트위터
     카드에서 위아래가 잘려 제목이 날아간다.

그래서 본문 그림은 폭을 줄여 webp 로 굽고, 대표 그림만 가운데를 1.91:1 로
잘라 따로 만든다. 자르는 위치는 눈으로 확인하고 정한 값이다(아래 LEAD).

다른 매거진 그림(tools/make_mz_images.py)은 PIL 로 직접 그리지만, 이 글은
앱 화면이 주인공이라 이미 만들어 둔 캐러셀을 쓴다.

    python tools/make_mz_gssg.py
"""
import io
import sys
from pathlib import Path

from PIL import Image

SRC = Path(r"C:\Users\jypark\Desktop\캐러셀\글씨사진관\글씨사진관-캐러셀")
OUT = Path(__file__).resolve().parent.parent / "static" / "mz"

# 본문에 넣을 슬라이드 → 내보낼 이름. 글의 각 절이 말하는 것을 그대로
# 보여주는 장만 고른다. 전부 넣으면 글이 아니라 캐러셀이 된다.
BODY = {
    "gssg-03.png": "gssg-tools",    # 네 개 버튼 — 화면 하나로 끝나는 편집
    "gssg-04.png": "gssg-fonts",    # 폰트 목록
    "gssg-05.png": "gssg-effect",   # 텍스트 효과
    "gssg-06.png": "gssg-date",     # 날짜스탬프
}
BODY_W = 900          # 본문 칸이 이보다 넓어지지 않는다. 2배 화면까지 감당한다.

# 대표 그림 — 1080×1350 에서 세로 한 띠를 1.91:1 로 잘라낸다.
# y 시작값은 눈으로 맞췄다. 위의 '안드로이드 무료 앱' 꼭지는 뺀다. 앱이 양쪽
# 스토어에 다 있어서 한쪽만 적힌 말이 대표 그림에 박히면 틀린 말이 된다.
LEAD_SRC = "gssg-01.png"
LEAD_OUT = "gssg-lead"
LEAD_TOP = 345
LEAD_SIZE = (1200, 630)


def save_webp(im: Image.Image, name: str, quality: int = 82) -> int:
    im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=6)
    path = OUT / (name + ".webp")
    path.write_bytes(buf.getvalue())
    return len(buf.getvalue())


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if not SRC.is_dir():
        print("원본 폴더가 없다: %s" % SRC)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    print("본문 그림")
    for src_name, out_name in BODY.items():
        im = Image.open(SRC / src_name)
        h = round(im.height * BODY_W / im.width)
        im = im.resize((BODY_W, h), Image.LANCZOS)
        n = save_webp(im, out_name)
        print("   %-14s → %-12s %dx%d  %.0fKB" % (src_name, out_name + ".webp", BODY_W, h, n / 1024))

    print("\n대표 그림 (og:image)")
    im = Image.open(SRC / LEAD_SRC)
    # 원본 폭 그대로 두고 세로만 1.91:1 만큼 잘라, 마지막에 1200×630 으로 줄인다.
    crop_h = round(im.width * LEAD_SIZE[1] / LEAD_SIZE[0])
    top = max(0, min(LEAD_TOP, im.height - crop_h))
    im = im.crop((0, top, im.width, top + crop_h)).resize(LEAD_SIZE, Image.LANCZOS)
    n = save_webp(im, LEAD_OUT, quality=84)
    print("   %-14s → %-12s %dx%d  %.0fKB (y %d 에서 %d 만큼)"
          % (LEAD_SRC, LEAD_OUT + ".webp", LEAD_SIZE[0], LEAD_SIZE[1], n / 1024, top, crop_h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
