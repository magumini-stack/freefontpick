"""폰트 조판 지표(x·w·d)를 재서 app/font_metrics.py 에 넣을 줄을 뽑는다.

왜 도구가 필요한가
----------------
`app/font_metrics.py` 는 값을 코드에 박아 둔다. 재는 데 폰트 한 종당 수 초가
들어서(woff2 압축 해제 + 글리프 재구성이 순수 파이썬이다) 512MB 운영
컨테이너에서 돌릴 수도, 업로드 응답에 끼울 수도 없기 때문이다. 그래서 로컬에서
한 번 재고 결과만 싣는다.

그동안 그 '한 번'을 매번 손으로 다시 짰다. 스크립트가 저장소에 없었던 탓인데,
폰트를 추가할 때마다 방식을 문서만 보고 다시 구현하는 셈이라 어긋날 여지가
있었다. 그래서 여기 남긴다.

재는 법 (app/font_metrics.py 의 정의 그대로)
------------------------------------------
    대표 글자  한글 : 가나다라마바사아자차카타파하   (자음 14개 대표음절)
               영문 : Hamburgefonts               (원 케이스)

    x  글자 높이 = mean( (ymax-ymin) / upm )      BoundsPen
    w  글자 폭   = mean( advance / upm )
    d  채움비율  = mean( |잉크면적| / bbox면적 )    AreaPen

측정 대상은 **운영이 대표 파일로 내려주는 그 파일**이다(/api/fonts/{id}/file).
화면에 그려지는 것과 같은 파일이어야 점수가 화면과 어긋나지 않는다.

CDN 웹폰트만 있는 폰트
--------------------
파일이 없으면 webfont_css_url 로 간다. 구글은 한글 폰트를 unicode-range 로
수십 조각을 내서 배포하므로, 대표 글자 14자가 각각 어느 조각에 들었는지 CSS 를
읽어 찾고 그 조각만 받아 글자별로 잰다. 조각을 하나로 합치지 않는 이유는
합칠 필요가 없어서다 — x·w·d 는 전부 글자별 평균이라 조각이 달라도 upm 으로
정규화하면 같은 눈금에 놓인다.

쓰는 법
------
    python tools/measure_metrics.py --check           # 기존 값 재현되는지만 확인
    python tools/measure_metrics.py --missing         # 표에 없는 폰트를 전부
    python tools/measure_metrics.py 238 239 240       # 특정 id 만

--check 를 먼저 돌린다. 이미 표에 있는 폰트를 다시 재서 같은 값이 나오는지
보는 것이라, 재는 법이 어긋나면 새 값을 믿을 수 없다.
"""
import argparse
import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from fontTools.pens.areaPen import AreaPen
from fontTools.pens.boundsPen import BoundsPen
import os
from fontTools.ttLib import TTFont

# 사이트 주소 — app/site.py 와 같은 환경변수를 본다.
# 도메인을 옮기면 SITE_URL 을 주고 돌린다.
BASE = os.getenv("SITE_URL", "https://freefontpick.co.kr").rstrip("/")
HOST = BASE.split("://", 1)[-1]   # 이미지에 글자로 찍을 때 쓴다
KO = "가나다라마바사아자차카타파하"
EN = "Hamburgefonts"

# 구글이 woff2 를 내려주게 하려면 최신 브라우저 UA 가 필요하다. 예전 UA 로
# 요청하면 ttf 를 주는데, 그건 화면에 실제로 그려지는 파일이 아니다.
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 재는 법이 맞는지 대볼 폰트. 성격이 다른 것으로 골랐다 —
# 굵은 고딕 · 초굵은 제목체 · 표준 고딕 · 명조 · 손글씨.
CHECK_IDS = [1, 17, 21, 56, 142]

_cache = {}


def fetch(url, browser=False):
    if url in _cache:
        return _cache[url]
    ua = UA_BROWSER if browser else "Mozilla/5.0 (compatible; freefontpick/1.0)"
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read()
    _cache[url] = data
    return data


def measure_glyphs(font: TTFont, chars: str):
    """글자마다 (높이비, 폭비, 채움비율). 없는 글자는 건너뛴다."""
    upm = font["head"].unitsPerEm or 1000
    cmap = font.getBestCmap()
    gs = font.getGlyphSet()
    hmtx = font["hmtx"]
    out = []
    for ch in chars:
        name = cmap.get(ord(ch))
        if not name or name not in gs:
            continue
        g = gs[name]
        bp = BoundsPen(gs)
        g.draw(bp)
        if not bp.bounds:
            continue                      # 빈 글리프 — 공백 등
        xmin, ymin, xmax, ymax = bp.bounds
        box = (xmax - xmin) * (ymax - ymin)
        if box <= 0:
            continue
        ap = AreaPen(gs)
        g.draw(ap)
        adv = hmtx[name][0] if name in hmtx.metrics else 0
        out.append(((ymax - ymin) / upm, adv / upm, abs(ap.value) / box))
    return out


def average(rows):
    if not rows:
        return None
    n = len(rows)
    return tuple(round(sum(r[i] for r in rows) / n, 3) for i in range(3))


# ── CDN 웹폰트 ──────────────────────────────────────────────────

_FACE = re.compile(r"@font-face\s*\{(.*?)\}", re.S)


def _css_faces(css: str, base_url: str):
    """CSS 에서 (family, weight, unicode-range 목록, 파일 주소) 를 뽑는다.

    주소는 상대 경로로 적힌 CSS 가 있어서(자체 호스팅 폰트가 대개 그렇다)
    CSS 주소를 기준으로 절대 주소로 바꾼다.
    """
    faces = []
    for body in _FACE.findall(css):
        m = re.search(r"src:[^;]*url\(([^)]+)\)", body)
        if not m:
            continue
        url = urllib.parse.urljoin(base_url, m.group(1).strip("'\" "))
        fam = re.search(r"font-family:\s*([^;]+)", body)
        family = fam.group(1).strip().strip("'\"") if fam else ""
        w = re.search(r"font-weight:\s*(\d+)", body)
        weight = int(w.group(1)) if w else 400
        ranges = []
        ur = re.search(r"unicode-range:\s*([^;]+)", body)
        if ur:
            for part in ur.group(1).split(","):
                part = part.strip().upper().replace("U+", "")
                if "-" in part:
                    a, b = part.split("-", 1)
                    ranges.append((int(a, 16), int(b, 16)))
                elif "?" in part:
                    ranges.append((int(part.replace("?", "0"), 16),
                                   int(part.replace("?", "F"), 16)))
                elif part:
                    ranges.append((int(part, 16), int(part, 16)))
        faces.append({"family": family, "weight": weight,
                      "ranges": ranges, "url": url})
    return faces


def measure_from_css(css_url: str, chars: str, want_weight: int,
                     want_family: str = ""):
    """조각난 웹폰트를 글자별로 잰다.

    조각마다 담은 글자가 다르므로 '이 글자를 가진 조각'을 찾아 그 파일에서
    그 글자만 잰다. 범위가 적히지 않은 조각(unicode-range 없음)은 통짜라
    어느 글자든 들어 있을 수 있으니 마지막 후보로 둔다.
    """
    css = fetch(css_url, browser=True).decode("utf-8", "replace")
    faces = _css_faces(css, css_url)
    if not faces:
        return None, "CSS 에서 @font-face 를 못 찾았다"

    # 한 CSS 에 여러 집안이 들어 있는 경우가 있다(자체 호스팅에서 흔하다).
    # 어느 것을 쓰는지는 폰트 기록의 webfont_family 가 안다.
    if want_family:
        same = [f for f in faces
                if f["family"].lower() == want_family.strip().lower()]
        if same:
            faces = same

    weights = sorted({f["weight"] for f in faces})
    weight = min(weights, key=lambda w: abs(w - want_weight))
    pool = [f for f in faces if f["weight"] == weight]

    rows = []
    for ch in chars:
        cp = ord(ch)
        cands = [f for f in pool
                 if any(a <= cp <= b for a, b in f["ranges"])]
        cands += [f for f in pool if not f["ranges"]]
        for f in cands:
            try:
                blob = fetch(f["url"], browser=True)
                tt = TTFont(io.BytesIO(blob), fontNumber=0, lazy=True)
            except Exception:
                continue
            got = measure_glyphs(tt, ch)
            tt.close()
            if got:
                rows.append(got[0])
                break
    if not rows:
        return None, "대표 글자를 담은 조각을 못 찾았다"
    return average(rows), "조각 %d개에서 %d자 (굵기 %d)" % (len(pool), len(rows), weight)


# ── 한 종 재기 ──────────────────────────────────────────────────

def measure_font(meta: dict):
    """(x, w, d), 설명. 못 재면 (None, 이유)."""
    chars = EN if meta.get("is_english") else KO
    want = int(meta.get("primary_weight") or 400)

    if meta.get("has_file"):
        try:
            blob = fetch("%s/api/fonts/%d/file" % (BASE, meta["id"]))
            tt = TTFont(io.BytesIO(blob), fontNumber=0, lazy=True)
        except Exception as e:
            return None, "대표 파일을 못 열었다: %s" % type(e).__name__
        rows = measure_glyphs(tt, chars)
        upm = tt["head"].unitsPerEm
        tt.close()
        if not rows:
            # 한글 폰트로 등록됐는데 한글이 없는 경우가 있다. 영문으로 다시.
            return None, "대표 글자가 파일에 없다"
        return average(rows), "대표 파일 · %d자 · upm %d" % (len(rows), upm)

    if meta.get("webfont_css_url"):
        val, why = measure_from_css(meta["webfont_css_url"], chars, want,
                                    meta.get("webfont_family") or "")
        return val, ("웹폰트 " + why if val else "웹폰트 " + why)

    return None, "파일도 웹폰트 CSS 도 없다"


def load_catalog():
    raw = fetch(BASE + "/api/fonts?weights=1").decode("utf-8")
    return {d["id"]: d for d in json.loads(raw)}


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", type=int)
    ap.add_argument("--check", action="store_true",
                    help="표에 이미 있는 폰트를 다시 재서 같은 값이 나오는지 본다")
    ap.add_argument("--missing", action="store_true",
                    help="표에 없는 폰트를 전부 잰다")
    args = ap.parse_args()

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    from app.font_metrics import FONT_METRICS

    cat = load_catalog()

    if args.check:
        print("재는 법 확인 — 표에 있는 값이 그대로 나오는가\n")
        okn = 0
        for fid in CHECK_IDS:
            want = FONT_METRICS.get(fid)
            got, why = measure_font(cat[fid])
            same = got == want
            okn += same
            print("  %3d %-20s 표 %s" % (fid, cat[fid]["name"], want))
            print("      %-24s 측정 %s  %s" % ("", got, "일치" if same else "<<< 다름"))
        print("\n%d/%d 일치" % (okn, len(CHECK_IDS)))
        return 0 if okn == len(CHECK_IDS) else 1

    ids = args.ids
    if args.missing:
        ids = sorted(i for i in cat if i not in FONT_METRICS)
    if not ids:
        print("잴 폰트를 지정하세요 (--missing 또는 id 나열)")
        return 1

    print("%d종 측정\n" % len(ids))
    ok, fail = [], []
    for fid in ids:
        meta = cat.get(fid)
        if not meta:
            fail.append((fid, "?", "등록되지 않은 id"))
            continue
        val, why = measure_font(meta)
        if val:
            ok.append((fid, meta["name"], val))
            print("  %3d %-24s x %.3f  w %.3f  d %.3f   %s"
                  % (fid, meta["name"], val[0], val[1], val[2], why))
        else:
            fail.append((fid, meta["name"], why))
            print("  %3d %-24s 못 쟀다 — %s" % (fid, meta["name"], why))

    if ok:
        print("\n── app/font_metrics.py 에 넣을 줄 ──")
        for fid, name, v in ok:
            print("    %-4d: (%.3f, %.3f, %.3f),   # %s" % (fid, v[0], v[1], v[2], name))
    if fail:
        print("\n못 잰 %d종:" % len(fail))
        for fid, name, why in fail:
            print("  %3d %-24s %s" % (fid, name, why))
    return 0


if __name__ == "__main__":
    sys.exit(main())
