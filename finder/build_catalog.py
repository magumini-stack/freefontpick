"""finder 가 쓰는 폰트 목록(/data/catalog.json)과 폰트 파일(/data/fonts)을 만든다.

    python build_catalog.py                 # 앱 API 에서 폰트픽 폰트를 받고, /data/tdtd 가 있으면 타닥타닥도 넣는다
    python build_catalog.py --stacks 1000   # 자주 쓰는 한글 1,000자의 글자 묶음 캐시까지 미리 굽는다(느리다)

폰트픽 폰트: 앱의 공개 API(/api/fonts?weights=1, /api/fonts/{id}/file/{w}.v{ver}.woff2)에서 받는다.
  실험실(fetch_fonts.py)과 같은 길 — 관리자가 폰트를 올리면 다시 돌리면 된다. woff2 는 PIL 이 바로 못 열어
  TTF 로 풀어 둔다(폰트 하나 여는 데 100ms 가 아니라 5ms 가 되게).
타닥타닥 폰트: /data/tdtd/fonts.json + /data/tdtd/full/f_<hash>.woff2 (tdtd-webfont 가 구운 2,350자판).
  git 에는 넣지 않는다(유료 폰트) — 서버에 따로 올린다. 배리어블은 굵기별로 떠 둔다.
  폰트픽과 겹치는 폰트(폰트픽의 와이즈폰트·상상토끼 제공분)는 폰트픽에서만 나오게 뺀다(글자 대조, 같은 집안끼리만).
"""
import argparse
import io
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
DATA = os.environ.get("FINDER_DATA", "/data")
APP = os.environ.get("FINDER_APP_URL", "http://app:8000")
FONTS = os.path.join(DATA, "fonts")
TDTD = os.path.join(DATA, "tdtd")
TDTD_LINK = {
    "타닥타닥": "https://tdtd.io/_subpage/kor/buy/list.php?viewMode=view&ca_id=&sel_search=&txt_search=&page=1&idx=6",
    "상상토끼": "https://tdtd.io/_subpage/kor/buy/list.php?viewMode=view&ca_id=&sel_search=&txt_search=&page=1&idx=11",
    "RakFont": "https://tdtd.io/_subpage/kor/buy/list.php?viewMode=view&ca_id=&sel_search=&txt_search=&page=1&idx=23",
}
FAMILY = {"와이즈폰트": "타닥타닥", "상상토끼": "상상토끼"}     # 폰트픽 제작사 → 겹침을 대 볼 타닥타닥 제작사
SAME_IOU = 0.85


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "freefontpick-finder"})
    return urllib.request.urlopen(req, timeout=120).read()


def to_ttf(src, dst):
    """woff2/woff/ttf → PIL 이 바로 여는 TTF. 이미 있으면 건너뛴다."""
    if os.path.exists(dst):
        return True
    from fontTools.ttLib import TTFont
    try:
        f = TTFont(src)
        f.flavor = None
        f.save(dst)
        return True
    except Exception as e:
        print("  ! 못 풀음", src, e)
        return False


def fetch_ffp():
    os.makedirs(FONTS, exist_ok=True)
    fonts = json.loads(get(APP + "/api/fonts?weights=1"))
    out = []
    for f in fonts:
        if not f.get("has_file"):
            continue
        ver = f.get("file_version", 0)
        weights = f.get("weights") or [f.get("primary_weight", 400)]
        faces = []
        for w in weights:
            dst = os.path.join(FONTS, "%03d_%d.ttf" % (f["id"], w))
            if not os.path.exists(dst):
                tmp = dst + ".src"
                try:
                    open(tmp, "wb").write(get(APP + "/api/fonts/%d/file/%d.v%d.woff2" % (f["id"], w, ver)))
                except Exception as e:
                    print("  ! 못 받음", f["id"], w, e)
                    continue
                ok = to_ttf(tmp, dst)
                os.remove(tmp)
                if not ok:
                    continue
            faces.append(dict(w=int(w), fn=dst))
        if faces:
            out.append(dict(id=f["id"], name=f["name"], maker=f.get("maker", ""), source="ffp",
                            is_english=bool(f.get("is_english")), link="/font/%d" % f["id"],
                            tags=f.get("tags", []), faces=faces))
    print("폰트픽 %d종 %d굵기" % (len(out), sum(len(x["faces"]) for x in out)))
    return out


def _mask(fn):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    try:
        f = ImageFont.truetype(fn, 48)
    except Exception:
        return None
    img = Image.new("L", (48 * 10, 80), 0)
    ImageDraw.Draw(img).text((8, 60), "가나다라마바사아", font=f, fill=255, anchor="ls")
    m = np.asarray(img) > 127
    ys, xs = np.nonzero(m)
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(xs) else None


def _iou(a, b):
    import numpy as np
    if abs(a.shape[1] - b.shape[1]) > 0.15 * max(a.shape[1], b.shape[1]):
        return 0.0
    h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    A = np.zeros((h, w), bool); B = np.zeros((h, w), bool)
    A[:a.shape[0], :a.shape[1]] = a; B[:b.shape[0], :b.shape[1]] = b
    return (A & B).sum() / max(1, (A | B).sum())


def fetch_tdtd(ffp):
    meta = os.path.join(TDTD, "fonts.json")
    if not os.path.exists(meta):
        print("타닥타닥 없음(%s) — 폰트픽만 넣는다" % meta)
        return []
    td = json.load(open(meta, encoding="utf-8"))["fonts"]
    vf_dir = os.path.join(TDTD, "vf")
    ttf_dir = os.path.join(TDTD, "ttf")
    os.makedirs(vf_dir, exist_ok=True)
    os.makedirs(ttf_dir, exist_ok=True)
    # 겹침 대조: 폰트픽 와이즈폰트·상상토끼 ↔ 같은 집안 타닥타닥
    fm = []
    for c in ffp:
        fam = FAMILY.get(next((k for k in FAMILY if k in c["maker"]), ""), None)
        if fam and not c["is_english"]:
            for fc in c["faces"]:
                m = _mask(fc["fn"])
                if m is not None:
                    fm.append((c["id"], fam, m))
    same = {}
    out = []
    for t in td:
        faces = []
        for fc in t["faces"]:
            src = os.path.join(TDTD, "full", "f_%s.woff2" % fc["h"])
            if not os.path.exists(src):
                continue
            if fc.get("style") == "Variable":
                for w, fn in _vf_instances(src, os.path.join(vf_dir, "t%d_%s" % (t["id"], fc["h"])), ttf_dir):
                    faces.append(dict(w=w, fn=fn, style="VF", h=fc["h"]))
                continue
            dst = os.path.join(ttf_dir, "f_%s.ttf" % fc["h"])
            if to_ttf(src, dst):
                faces.append(dict(w=int(fc["w"]), fn=dst, style=fc.get("style", ""), h=fc["h"]))
        if not faces:
            continue
        if t["vendor"] in {f for _, f, _ in fm}:
            for fc in faces:
                m = _mask(fc["fn"])
                if m is None:
                    continue
                for fid, fam, fmask in fm:
                    if fam == t["vendor"] and _iou(m, fmask) >= SAME_IOU:
                        same[t["id"]] = fid
        if t["id"] in same:
            continue
        out.append(dict(id="t%d" % t["id"], name=t["ko"], maker=t["vendor"], source="tdtd", is_english=False,
                        link=TDTD_LINK.get(t["vendor"], TDTD_LINK["타닥타닥"]), tags=[t.get("cat", "")], faces=faces))
    print("타닥타닥 %d종(폰트픽과 겹쳐 뺀 것 %d)" % (len(out), len(same)))
    return out


def _vf_instances(path, key, ttf_dir):
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    f = TTFont(path)
    if "fvar" not in f:
        return []
    axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in f["fvar"].axes}
    if "wght" not in axes:
        return []
    lo, df, hi = axes["wght"]
    out = []
    for w in sorted({max(lo, min(hi, v)) for v in (lo, 300, 400, 500, 700, 900, hi)}):
        fn = "%s_w%d.ttf" % (key, int(w))
        if not os.path.exists(fn):
            inst = instantiateVariableFont(TTFont(path), {t: (int(w) if t == "wght" else axes[t][1]) for t in axes})
            inst.flavor = None
            inst.save(fn)
        out.append((int(w), fn))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stacks", type=int, default=0, help="미리 구울 한글 글자 수(자주 쓰는 순)")
    a = ap.parse_args()
    os.makedirs(DATA, exist_ok=True)
    t0 = time.time()
    ffp = fetch_ffp()
    td = fetch_tdtd(ffp)
    cat = ffp + td
    json.dump(cat, open(os.path.join(DATA, "catalog.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("목록 저장: %d종 %d굵기 (%.0fs)" % (len(cat), sum(len(x["faces"]) for x in cat), time.time() - t0))
    if a.stacks > 0:
        import engine_v0 as E
        db = E.FontDB(os.path.join(DATA, "catalog.json"))
        db.MAX_STACKS = 4
        chars = frequent_hangul(a.stacks)
        for k, ch in enumerate(chars):
            db.stack(ch)
            if (k + 1) % 50 == 0:
                print("  묶음 %d/%d (%.0fs)" % (k + 1, len(chars), time.time() - t0), flush=True)


def frequent_hangul(n):
    """자주 쓰는 한글 순서 — 여기 없는 글자는 처음 물어볼 때 만들어 캐시된다."""
    common = ("의이다에는을가하고를은한로지서으것이수아그들자기시상해년어리사대인전내주정성라"
              "제부장도우나동공소경보무비마원계신조모진문화국개거세중요학교여도금물영업방식화면"
              "글씨폰트찾기추천이미지디자인무료손글씨명조고딕제목본문영문한글")
    seen = []
    for ch in common:
        if 0xAC00 <= ord(ch) <= 0xD7A3 and ch not in seen:
            seen.append(ch)
    cp = 0xAC00
    while len(seen) < n and cp <= 0xD7A3:
        ch = chr(cp)
        if ch not in seen:
            seen.append(ch)
        cp += 1
    return seen[:n]


if __name__ == "__main__":
    main()
