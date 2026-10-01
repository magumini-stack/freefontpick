"""타닥타닥 구독 폰트 미리보기 자료를 폰트픽으로 옮긴다 (2026-10-01).

메인·전체 폰트 보기의 '구독 폰트' 칸이 쓴다(static/ffp-subscribe.js).

어디서 오나
-----------
타닥타닥 폰트보기(tdtd.io/fonts/about)용으로 이미 구워 둔 자료를 그대로 쓴다.

    Desktop/projects/tdtd-webfont/out/fonts.json      폰트 목록·분류·제작사·묶음(g)
    Desktop/projects/tdtd-webfont/out/light/f_<h>.woff2  견본 문구 글자만 담은 웹폰트(평균 13KB)

tdtd.io 의 /fontfile.php 는 Referer 를 검사해 다른 사이트에서 못 부른다. 그래서
파일을 폰트픽 서버에 둔다(사용자님 결정). 유료 폰트라 견본 문구 글자만 담긴
light 판만 가져온다 — 2,350자 full 판은 옮기지 않는다.

폰트 하나에 굵기가 여럿이면 400(없으면 첫 번째) 한 벌만 쓴다.

묶음 → 구독 플랜 (사용자님 결정 2026-10-01, 폰트별 상품 페이지는 없다)
    타닥타닥            Basic Plan       idx 6
    상상토끼            Premium Plan     idx 11
    상상토끼 캘리그라피   Calli Font Plan  idx 26   (상상토끼에도 있으면 Premium)
    RakFont            Basic Plus Plan  idx 23

    python tools/build_subfonts.py [tdtd-webfont 경로]
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent.parent / "tdtd-webfont"
OUT = ROOT / "static" / "subfonts"

PLAN = {
    "타닥타닥": ("Basic Plan", 6),
    "상상토끼": ("Premium Plan", 11),
    "상상토끼 캘리그라피": ("Calli Font Plan", 26),
    "RakFont": ("Basic Plus Plan", 23),
}
ORDER = ["타닥타닥", "상상토끼", "상상토끼 캘리그라피", "RakFont"]


def main():
    data = json.loads((SRC / "out" / "fonts.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    keep = set()
    fonts = []
    for f in data["fonts"]:
        face = next((x for x in f["faces"] if x["w"] == 400), f["faces"][0])
        src = SRC / "out" / "light" / f"f_{face['h']}.woff2"
        if not src.is_file():
            print("파일 없음:", f["ko"], src.name)
            continue
        dst = OUT / f"{face['h']}.woff2"
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copyfile(src, dst)
        keep.add(dst.name)
        g = min(f["g"], key=ORDER.index)        # 두 묶음이면 앞쪽(상상토끼 → Premium)
        plan, idx = PLAN[g]
        fonts.append({
            "n": f["ko"], "v": f["vendor"], "c": f["cat"], "h": face["h"], "w": face["w"],
            "s": len(f["faces"]), "p": plan, "i": idx, **({"new": 1} if f.get("new") else {}),
        })
    for old in OUT.glob("*.woff2"):
        if old.name not in keep:
            old.unlink()
    doc = {"sample": data["sample"], "fonts": fonts}
    (OUT / "fonts.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                                    encoding="utf-8")
    size = sum(p.stat().st_size for p in OUT.glob("*.woff2"))
    print(f"구독 폰트 {len(fonts)}종 · 웹폰트 {len(keep)}개 {size/1e6:.1f}MB → {OUT}")


if __name__ == "__main__":
    main()
