"""폰트 찾기 엔진 v0 — 학습 없이, 읽은 글자를 폰트마다 그려서 한 자씩 견준다.

흐름
  1. 줄 잘라내기   OCR 이 준 사각형을 곧게 펴서 한 줄 이미지로 만든다
  2. 글자 떼어내기 배경색에서 먼 픽셀을 글자로 본다(색 글자·색 배경도 되게)
  3. 한 자씩 자르기 OCR 이 준 글자별 x 범위로 자르고 잉크에 맞춰 조인다
  4. 견주기        폰트마다 같은 글자를 그려 모양·획 굵기·장평을 비교한다
  5. 줄 전체       글자 높이의 들쭉날쭉함(탈네모)도 비교한다
"""
import collections
import io
import json
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

_POP = np.array([bin(i).count("1") for i in range(256)], np.uint8)   # 바이트 popcount 표
RS = 96          # 폰트를 그리는 크기(px)
N = 48           # 비교용 정규화 칸
DT_Q = 4         # 폰트 쪽 윤곽 거리는 1/4칸 단위 uint8 로 들고 있는다(FontDB.stack)
DT_CAP = 8.0     # 윤곽 거리는 8칸에서 자른다 — 떨어진 티끌 하나가 평균을 끌고 가지 않게
# 점수 섞기: (윤곽 거리, 획 굵기 차, 장평 차, 줄 탈네모, 겹침(1-IoU), 윤곽 밀도 차, 굵기 들쭉날쭉함 차, 방향 분포 차).
# WMIX=1,2,1.5,2,0.5,0.7,1.5,2 처럼 바꿔 시험
WMIX = tuple(float(x) for x in __import__("os").environ.get("WMIX", "1,2,1.5,2,0.5,0.7,1.5,2").split(","))


# ── 폰트 목록 ───────────────────────────────────────────────────

def coarse_cats(tags, is_english=False):
    """사이트 태그(폰트픽)·cat(타닥타닥)를 굵은 갈래로. 결과 목록을 1위와 같은 갈래로 추리는 데 쓴다
    (2026-09-22 사용자님: 손글씨 질의에 붓글씨체가, 고딕 질의에 장식체가 끼면 안 된다)."""
    out = set()
    for t in tags or []:
        t = str(t)
        if "손글씨" in t or "자막" in t:
            out.add("손글씨")
        if "캘리" in t:
            out.add("캘리")
        if "고딕" in t or "굴림" in t or "UI" in t:
            out.add("고딕")
        if "명조" in t or "세리프" in t or "바탕" in t:
            out.add("명조")
        if "디스플레이" in t or "디자인" in t or "장식" in t or "펜시" in t or "제목용" in t or "썸네일" in t:
            out.add("디스플레이")
        if "영어" in t:
            out.add("영어")
    if is_english:
        out.add("영어")
    return out


class _CmapView:
    """it["cmap"] 호환용 — `ord(ch) in it["cmap"]` 만 된다(비트 표를 본다)."""
    __slots__ = ("db", "i")

    def __init__(self, db, i):
        self.db, self.i = db, i

    def __contains__(self, cp):
        return cp < 65536 and bool(self.db.cmap_bits[self.i, cp >> 3] & (0x80 >> (cp & 7)))


class FontDB:
    """폰트 목록. 두 가지 모양을 읽는다.

    catalog.json      폰트픽만 — {"id", "files": {굵기: 경로}} (처음 만든 모양)
    catalog_all.json  폰트픽 + 타닥타닥 — {"id", "faces": [{"w", "fn"}], "source", "link", "maker"}
                      (build_catalog_all.py, 2026-09-22). 타닥타닥 id 는 "t123" 처럼 글자다.
    """

    # 한 번에 열어 두는 폰트(PIL) 수. 1,279벌을 다 열어 두면 300MB 라 서버(2GB)는 64. 실험실처럼 글자 묶음을
    # 새로 굽는 쪽은 크게(FINDER_MAX_FONTS=2000) — 묶음 하나에 1,279벌을 다 열어야 해서 64면 파일을 계속 다시 연다.
    MAX_FONTS = int(os.environ.get("FINDER_MAX_FONTS", "64"))

    def __init__(self, catalog_path="catalog.json", cmap_cache="cmaps.json"):
        self.cat = json.load(open(catalog_path, encoding="utf-8"))
        cmap_path = os.path.join(os.path.dirname(os.path.abspath(catalog_path)) or ".", cmap_cache)
        try:
            cmaps = {k: set(v) for k, v in json.load(open(cmap_path)).items()}
        except FileNotFoundError:
            cmaps = {}
        self.items = []          # dict(fid, weight, name, is_english, fn) — 폰트 자체는 font(i) 로 지연 로드
        self.info = {}           # fid → dict(name, maker, source, link)
        self.cats = {}           # fid → 굵은 갈래 집합 {'손글씨','고딕','명조','디스플레이','캘리','영어'} (비면 모름)
        self._fonts = collections.OrderedDict()
        dirty = False
        rows = []
        for c in self.cat:
            if "faces" in c:
                faces = [(fc["w"], fc["fn"], fc.get("h")) for fc in c["faces"]]
            else:
                faces = [(int(w), fn, None) for w, fn in c["files"].items()]
            self.info[c["id"]] = dict(name=c["name"], maker=c.get("maker", ""),
                                      source=c.get("source", "ffp"),
                                      link=c.get("link", "/font/%s" % c["id"]))
            self.cats[c["id"]] = coarse_cats(c.get("tags", []), c["is_english"])
            base = os.path.dirname(os.path.abspath(catalog_path))
            for w, fn, h in faces:
                # 상대 경로는 목록 파일이 있는 폴더 기준 — 서비스(finder/)가 실험실 목록을 쓸 때 다른 폴더에서 돌아도 열리게.
                # cmap 캐시의 키는 목록에 적힌 문자열 그대로 둔다(절대 경로로 바꾸면 캐시를 다시 만든다).
                path = fn if os.path.isabs(fn) else os.path.join(base, fn)
                if fn not in cmaps:
                    cm = self._cmap(path)
                    if not cm:
                        continue                          # 못 여는 파일
                    cmaps[fn] = cm
                    dirty = True
                elif not cmaps[fn]:
                    continue
                self.items.append(dict(fid=c["id"], weight=int(w), name=c["name"],
                                       is_english=c["is_english"], fn=path, fn_key=fn, h=h))
                rows.append(cmaps[fn])
        if dirty:
            json.dump({k: sorted(v) for k, v in cmaps.items()}, open(cmap_path, "w"))
        # cmap 은 비트 표(굵기 × 65536비트 = 8KB) — 파이썬 set 으로 들고 있으면 1,279벌에 270MB 였다
        bits = np.zeros((len(self.items), 65536 // 8), np.uint8)
        for i, cm in enumerate(rows):
            cps = np.fromiter((cp for cp in cm if 0 <= cp < 65536), dtype=np.int64)
            if len(cps):
                # 같은 바이트에 여러 비트가 들어가므로 |= 가 아니라 bitwise_or.at (겹치는 자리는 한 번만 반영된다)
                np.bitwise_or.at(bits[i], cps >> 3, (0x80 >> (cps & 7)).astype(np.uint8))
        self.cmap_bits = bits
        for i, it in enumerate(self.items):
            it["cmap"] = _CmapView(self, i)
        self.is_eng = np.array([it["is_english"] for it in self.items], bool)
        self.stacks = collections.OrderedDict()
        # 디스크 캐시: 폰트 목록(파일 경로·굵기 순서)이 같을 때만 재사용 — 목록이 바뀌면 태그가 바뀐다
        import hashlib
        tag = hashlib.md5("|".join("%s:%s" % (it["fn_key"], it["weight"]) for it in self.items).encode("utf-8")).hexdigest()[:10]
        self.stack_dir = os.path.join(os.path.dirname(os.path.abspath(catalog_path)) or ".", "stacks", tag)
        os.makedirs(self.stack_dir, exist_ok=True)
        self.typo_memo = {}      # (face i, ch) → typo 특징 dict

    @staticmethod
    def _load(fn):
        try:
            return ImageFont.truetype(fn, RS)
        except Exception:
            try:  # 프리타입이 못 여는 woff2 는 TTF 로 풀어서 연다
                from fontTools.ttLib import TTFont
                f = TTFont(fn)
                f.flavor = None
                b = io.BytesIO()
                f.save(b)
                b.seek(0)
                return ImageFont.truetype(b, RS)
            except Exception:
                return None

    def font(self, i):
        """굵기 i 의 PIL 폰트 — 필요할 때 열고 MAX_FONTS 개만 들고 있는다."""
        f = self._fonts.get(i)
        if f is not None:
            self._fonts.move_to_end(i)
            return f
        f = self._load(self.items[i]["fn"])
        self._fonts[i] = f
        while len(self._fonts) > self.MAX_FONTS:
            self._fonts.popitem(last=False)
        return f

    def has(self, i, ch):
        cp = ord(ch)
        return cp < 65536 and bool(self.cmap_bits[i, cp >> 3] & (0x80 >> (cp & 7)))

    @staticmethod
    def _cmap(fn):
        from fontTools.ttLib import TTFont
        try:
            return set((TTFont(fn, lazy=True).getBestCmap() or {}).keys())
        except Exception:
            return set()

    def glyph(self, i, ch):
        """한 굵기의 한 글자 특징. 글자가 없으면 None. (살펴보기용 — 견주기는 stack 을 쓴다)"""
        if not self.has(i, ch):
            return None
        font = self.font(i)
        if font is None:
            return None
        img = Image.new("L", (RS * 3, RS * 2), 0)
        ImageDraw.Draw(img).text((RS // 2, RS * 3 // 2), ch, font=font, fill=255, anchor="ls")
        return glyph_features(np.asarray(img) > 127, baseline=RS * 3 // 2, em=RS)

    MAX_STACKS = int(os.environ.get("FINDER_MAX_STACKS", "200"))   # 글자당 ≈ 3.5MB(dt 3MB + 비트 마스크 0.4MB). 서버(2GB)는 30~40

    def stack(self, ch):
        """이 글자가 있는 모든 굵기의 특징을 배열 한 벌로 묶는다 — rank 가 한 번에 견준다.

        dt: (굵기 수, N*N) 윤곽까지 거리 ×DT_Q (uint8)
        eidx/eoff: 굵기마다 윤곽 픽셀 번호를 이어 붙인 것과 그 시작 위치
        글자 하나에 1,279벌이면 약 3.4MB. 전에는 (굵기, 글자)마다 float64 배열을 따로 들고 있어
        실제 샘플 173장을 돌리다 메모리가 10GB 를 넘었다(2026-09-22).
        """
        s = self.stacks.get(ch)
        if s is not None:
            self.stacks.move_to_end(ch)
            return s
        fn = os.path.join(self.stack_dir, "%05x.npz" % ord(ch))
        if os.path.exists(fn):
            try:
                z = np.load(fn)
                s = {k: z[k] for k in z.files}
                if "n_packed" in s:
                    s["np"] = s.pop("n_packed")
                self.stacks[ch] = s
                while len(self.stacks) > self.MAX_STACKS:
                    self.stacks.popitem(last=False)
                return s
            except Exception:
                pass
        idx, dts, ns, eidx, eoff, st, asp, hs, scv, oh = [], [], [], [], [0], [], [], [], [], []
        for i in range(len(self.items)):
            g = self.glyph(i, ch)
            if g is None:
                continue
            idx.append(i)
            dts.append(np.minimum(np.rint(np.minimum(g["dt"], DT_CAP) * DT_Q), 255).astype(np.uint8).ravel())
            ns.append(g["n"].ravel().astype(np.uint8))
            e = np.flatnonzero(g["edge"]).astype(np.uint16)
            eidx.append(e)
            eoff.append(eoff[-1] + len(e))
            st.append(g["stroke"]); asp.append(g["aspect"]); hs.append(g["h"]); scv.append(g["scv"]); oh.append(g["oh"])
        s = dict(idx=np.array(idx, int))
        if idx:
            n_ = np.stack(ns)
            nsum = n_.sum(axis=1).astype(np.float32)
            s.update(dt=np.stack(dts), np=np.packbits(n_, axis=1), nsum=nsum,
                     eidx=np.concatenate(eidx), eoff=np.array(eoff),
                     dens=np.diff(eoff) / np.maximum(1.0, nsum),      # 윤곽 픽셀 / 잉크 픽셀 — 속 빈·줄무늬 폰트는 크다
                     scv=np.array(scv, np.float32), oh=np.stack(oh),
                     stroke=np.array(st), aspect=np.array(asp), h=np.array(hs, float))
        self.stacks[ch] = s
        while len(self.stacks) > self.MAX_STACKS:
            self.stacks.popitem(last=False)
        if idx:
            try:
                save = {k: v for k, v in s.items() if k != "np"}
                save["n_packed"] = s["np"]
                tmp = fn + ".tmp.npz"
                np.savez(tmp, **save)
                os.replace(tmp, fn)
            except Exception:
                pass
        return s


# ── 마스크 → 특징 ───────────────────────────────────────────────

def tight(m):
    ys, xs = np.flatnonzero(m.any(axis=1)), np.flatnonzero(m.any(axis=0))
    if len(xs) == 0:
        return None
    return m[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1], (xs[0], ys[0], xs[-1] + 1, ys[-1] + 1)


def edt(m):
    """참 픽셀마다 가장 가까운 거짓 픽셀까지 거리. scipy 와 값이 같고 4배 빠르다(배열 밖은 참으로 친다).

    OpenCV 는 여러 갈래로 나눠 계산해서 끝자리(1e-7)가 부를 때마다 달라진다. 그대로 두면
    stroke_ratio 의 '국소 최대' 판정이 흔들려 같은 사진의 순위가 실행마다 바뀌었다 → 반올림.
    """
    d = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    return np.round(d, 3)


_CROSS = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))


def normalize(m):
    """가로세로 비를 지키며 N×N 칸 가운데에 넣는다."""
    h, w = m.shape
    s = (N - 4) / max(h, w)
    nh, nw = max(1, round(h * s)), max(1, round(w * s))
    small = cv2.resize(m.astype(np.uint8) * 255, (nw, nh), interpolation=cv2.INTER_AREA) > 96
    out = np.zeros((N, N), bool)
    y0, x0 = (N - nh) // 2, (N - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = small
    return out


def stroke_stats(m):
    """(획 굵기 / 글자 높이, 굵기의 들쭉날쭉함). 굵기는 잉크 안쪽 거리 변환의 뼈대 값으로 잰다.

    들쭉날쭉함 = 뼈대 굵기의 표준편차/평균 — 붓글씨·캘리는 크고, 펜 손글씨·고딕은 작다.
    9/22 사용자님: 펜 손글씨 질의에 붓글씨체(낭만있구미체)가 끼면 안 된다.
    """
    if m.sum() == 0:
        return 0.0, 0.0
    dt = edt(m)
    # 뼈대 근처(국소 최대) 값의 중앙값 ×2 = 대표 획 굵기
    mx = cv2.dilate(dt, np.ones((3, 3), np.uint8))
    ridge = (dt == mx) & (dt > 0.5)
    v = dt[ridge]
    w = 2 * np.median(v) if len(v) else 2 * dt.max()
    cv_ = float(v.std() / max(1e-6, v.mean())) if len(v) > 3 else 0.0
    return float(w / max(1, m.shape[0])), cv_


def stroke_ratio(m):
    return stroke_stats(m)[0]


def orient_hist(n, bins=6):
    """정규화 글자의 윤곽 방향 분포(0~180°, 6칸, 기울기 크기로 가중). 고딕은 0°·90° 에 몰리고
    손글씨·붓글씨는 고루 퍼진다 — '느낌'이 다른 폰트를 가른다."""
    f = n.astype(np.float32)
    gx = cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    ang = np.arctan2(gy, gx) % np.pi
    h, _ = np.histogram(ang, bins=bins, range=(0, np.pi), weights=mag)
    tot = h.sum()
    return (h / tot).astype(np.float32) if tot > 0 else np.full(bins, 1.0 / bins, np.float32)


def glyph_features(mask, baseline=None, em=None):
    t = tight(mask)
    if t is None:
        return None
    m, (x0, y0, x1, y1) = t
    n = normalize(m)
    edge = n & ~(cv2.erode(n.astype(np.uint8), _CROSS) > 0)     # n 은 가장자리에 2칸 여백이 있다
    dt_out = edt(~n)
    st, scv = stroke_stats(m)
    return dict(
        n=n, edge=edge, dt=dt_out, oh=orient_hist(n), scv=scv,
        aspect=m.shape[1] / m.shape[0],
        stroke=st,
        h=m.shape[0], w=m.shape[1],
        top=(baseline - y0) / em if baseline is not None else None,
        bottom=(baseline - y1) / em if baseline is not None else None,
    )


def chamfer(a, b):
    """두 정규화 글자의 윤곽 거리(칸 단위). 작을수록 닮았다."""
    if not a["edge"].any() or not b["edge"].any():
        return 10.0
    return 0.5 * (b["dt"][a["edge"]].mean() + a["dt"][b["edge"]].mean())


# ── 이미지 → 한 줄 → 글자들 ─────────────────────────────────────

def rectify(img, quad, pad_ratio=0.12):
    """OCR 사각형을 곧게 편 줄 이미지. 위아래로 조금 여유를 준다."""
    q = np.array(quad, np.float32)
    w = int(max(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3])))
    h = int(max(np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1])))
    pad = int(h * pad_ratio)
    dst = np.array([[pad, pad], [pad + w, pad], [pad + w, pad + h], [pad, pad + h]], np.float32)
    M = cv2.getPerspectiveTransform(q, dst)
    out = cv2.warpPerspective(img, M, (w + 2 * pad, h + 2 * pad), borderMode=cv2.BORDER_REPLICATE)
    return out, M, pad


def text_mask(line_rgb):
    """배경색에서 먼 픽셀 = 글자. 배경색은 가장자리 픽셀의 중앙값."""
    lab = cv2.cvtColor(line_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    b = 2
    border = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                             lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    d = np.linalg.norm(lab - bg, axis=2)
    d8 = np.clip(d / max(1e-6, d.max()) * 255, 0, 255).astype(np.uint8)
    th, m = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = m > 0
    # 아주 작은 티끌은 지운다(획 조각은 남도록 기준을 낮게)
    lab_, n = ndimage.label(m)
    if n:
        sizes = ndimage.sum(m, lab_, range(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sizes >= max(4, 0.0005 * m.size)
        m = keep[lab_]
    return m


def keep_band(mask, pad):
    """줄 띠 밖에 중심이 있는 덩어리를 지운다.

    rectify 가 위아래로 여유(pad)를 두기 때문에 윗줄·아랫줄 글자의 조각이
    딸려 들어온다. 그 조각이 글자 상자에 섞이면 글자 비율이 통째로 어긋나
    엉뚱한 폰트가 닮았다고 나왔다(실측: 정답이 296종 중 250위 밖).
    """
    H = mask.shape[0]
    lo, hi = pad, H - pad
    lab, n = ndimage.label(mask)
    if not n:
        return mask
    keep = np.zeros(n + 1, bool)
    for k, sl in enumerate(ndimage.find_objects(lab), start=1):
        y0, y1 = sl[0].start, sl[0].stop
        cy = (y0 + y1) / 2
        overlap = max(0, min(y1, hi) - max(y0, lo)) / max(1, y1 - y0)
        keep[k] = lo <= cy <= hi or overlap >= 0.6
    return keep[lab]


def main_band(mask):
    """상자 안에 줄이 둘 이상 들어 있으면 잉크가 가장 많은 줄만 남긴다.

    OCR 이 제목과 바로 아래 부제를 한 상자로 묶는 일이 잦다(읽은 글자는 제목뿐).
    줄 전체의 가로 투영에서 빈 행이 이어지는 곳을 줄 경계로 본다 — 한 글자 안의
    받침 틈은 글자마다 높이가 달라 줄 전체로 보면 거의 비지 않는다.
    """
    rows = mask.any(axis=1)
    runs, start = [], None
    for y, v in enumerate(rows):
        if v and start is None:
            start = y
        elif not v and start is not None:
            runs.append([start, y]); start = None
    if start is not None:
        runs.append([start, len(rows)])
    if len(runs) <= 1:
        return mask
    merged = [runs[0]]
    for r in runs[1:]:
        p = merged[-1]
        if r[0] - p[1] < 0.08 * max(p[1] - p[0], r[1] - r[0]):
            p[1] = r[1]
        else:
            merged.append(r)
    if len(merged) == 1:
        return mask
    ink = [mask[a:b].sum() for a, b in merged]
    a, b = merged[int(np.argmax(ink))]
    lab, n = ndimage.label(mask)
    keep = np.zeros(n + 1, bool)
    for k, sl in enumerate(ndimage.find_objects(lab), start=1):
        y0, y1 = sl[0].start, sl[0].stop
        keep[k] = max(0, min(y1, b) - max(y0, a)) >= 0.5 * (y1 - y0)
    return keep[lab]


def deshear(mask):
    """기울인(이탤릭) 글자를 세운다. 글자 사이 빈 세로줄이 가장 많이 생기는 기울기를 고른다.

    기울어진 줄은 글자 사이에 빈 세로줄이 없어 세로로 자르면 글자가 반씩 잘린다.
    반듯한 글자에는 손대지 않도록, 빈 줄이 뚜렷하게(8% 넘게) 늘 때만 바꾼다.
    """
    H, W = mask.shape
    cy = H / 2
    m8 = mask.astype(np.uint8) * 255

    def occupied(a):
        Wn = W + int(abs(a) * H) + 2
        Mx = np.float32([[1, a, (abs(a) * H) / 2 - a * cy + 1], [0, 1, 0]])
        s = cv2.warpAffine(m8, Mx, (Wn, H), flags=cv2.INTER_NEAREST) > 0
        return int(s.any(axis=0).sum()), s

    # 1) 잉크의 2차 모멘트로 기울기를 잰다(mu11/mu02) — 굵고 촘촘한 이탤릭은 세워도 빈 세로줄이
    #    안 생겨 아래 2) 방법이 못 잡았다(9/22 '호수비 진다운 씨'). 반듯한 글씨는 0 근처라 건드리지 않는다.
    base, _ = occupied(0.0)
    mo = cv2.moments(m8, binaryImage=True)
    if mo["mu02"] > 1e-6:
        a = float(np.clip(mo["mu11"] / mo["mu02"], -0.6, 0.6))
        if abs(a) >= 0.08:
            occ, s = occupied(-a)
            # 세운 뒤 잉크 든 세로줄이 늘면 잘못 잰 것(반듯한 글씨에 '..!' 같은 게 붙어 모멘트가 비뚤어진 경우) → 버린다
            if occ <= base:
                return s, -a
    # 2) 글자 사이 빈 세로줄이 가장 많이 생기는 기울기
    best = (base, 0.0, mask)
    for a in np.linspace(-0.45, 0.45, 19):
        if abs(a) < 1e-6:
            continue
        occ, s = occupied(float(a))
        if occ < best[0]:
            best = (occ, float(a), s)
    if best[1] != 0.0 and best[0] < base * 0.92:
        return best[2], best[1]
    return mask, 0.0


def split_glyphs(mask, M, pad, char_boxes, line_coords=False, how="dp"):
    """OCR 글자 상자를 길잡이로 삼아, 글자 사이의 빈 세로줄에서 자른다.
    char_boxes 는 원본 이미지 좌표(M 으로 옮긴다). line_coords=True 면 이미 줄 이미지 좌표.

    OCR 의 글자 상자는 인식 과정(CTC)에서 거꾸로 짐작한 위치라 줄 끝으로 갈수록
    밀린다. 그대로 자르면 글자 반쪽이 이웃 칸으로 넘어간다. 그래서 상자의
    가운데만 믿고, 이웃한 두 가운데 사이에서 잉크가 가장 적은 세로줄을 경계로 삼는다.

    세로쓰기(글자 가운데가 위아래로 늘어선 줄)는 줄을 눕혀서 같은 방법으로 자르고
    자른 글자를 다시 세운다 — 가로로만 자르던 때는 세로 제목이 통째로 한두 조각이 됐다.
    """
    chars, cx, cy = [], [], []
    for ch, box in char_boxes:
        if ch.isspace():
            continue
        pts = np.asarray(box, np.float32) if line_coords else cv2.perspectiveTransform(np.array([box], np.float32), M)[0]
        chars.append(ch)
        cx.append(float(pts[:, 0].mean()))
        cy.append(float(pts[:, 1].mean()))
    if not chars:
        return []
    if len(chars) >= 2 and np.ptp(cy) > 2 * max(1.0, np.ptp(cx)):
        return [(ch, m.T) for ch, m in _split_line(mask.T, pad, chars, cy, shear_ok=False, how=how)]
    return _split_line(mask, pad, chars, cx, how=how)


def _cut_positions(prof, centers, H):
    """글자 가운데 N개(x, 왼→오) → 자를 자리 N-1개. 잉크가 적은 세로줄 띠들 중에서 DP 로 고른다.

    비용 = 잉크(빈 띠 0, 좁은 빈 띠 0.3, 얕은 골은 잉크 비율×10) + 2×|가운데 둘의 중간에서 떨어진 거리|/간격
           + 1.5×|잘린 폭 − 대표 폭|/대표 폭
    빈 곳만 보면 안 되는 까닭(9/22 '파우치 털기는'): 자모가 느슨한 손글씨는 글자 사이는 붙고(ㅏ와 우)
    글자 속은 비어(ㅍ|ㅏ, ㅊ|ㅣ) '파'가 'ㅍ'+'ㅏ우'로 잘렸다. OCR 가운데 둘의 중간(밀림이 서로 상쇄돼 꽤 정확하다)과
    글자 폭이 고르다는 점을 같이 쓰면 자모 틈보다 붙은 경계를 고른다. 넓은 빈 띠(높이의 8% 이상)는 거의 글자 사이다.
    """
    N = len(centers)
    if N <= 1:
        return []
    ink = np.nonzero(prof)[0]
    x0, x1 = int(ink[0]), int(ink[-1]) + 1
    top = max(1.0, float(prof.max()))
    mids = [(a + b) / 2 for a, b in zip(centers, centers[1:])]
    wexp = max(4.0, float(np.median(np.diff(centers))) if N >= 3 else (x1 - x0) / N)
    low = prof <= 0.12 * top
    cands, st = [], None
    for i, e in enumerate(list(low) + [False]):
        if e and st is None:
            st = i
        elif not e and st is not None:
            if i > x0 and st < x1:
                frac = float(prof[st:i].mean() / top)
                cost = (0.0 if i - st >= 0.08 * H else 0.3) if frac <= 0 else 10.0 * frac
                cands.append(((st + i) // 2, cost))
            st = None
    layers, prev = [], None
    for i, (a, b) in enumerate(zip(centers, centers[1:])):
        d = max(1.0, b - a)
        lo, hi = a + 0.1 * d, b - 0.1 * d
        cs = [c for c in cands if lo <= c[0] <= hi]
        if not cs:
            l, h = int(max(x0, lo)), int(min(x1 - 1, hi))
            if h <= l:
                cs = [(int((a + b) / 2), 1.0)]
            else:
                seg = prof[l:h + 1]
                j = int(np.argmin(seg))
                cs = [(l + j, 10.0 * float(seg[j] / top))]
        layer = []
        for x, cost in cs:
            base = cost + 2.0 * abs(x - mids[i]) / d
            if prev is None:
                layer.append((base + 1.5 * abs((x - x0) - wexp) / wexp, x, -1))
                continue
            best = (1e9, -1)
            for k, (pt, px, _) in enumerate(prev):
                if px >= x:
                    continue
                t = pt + base + 1.5 * abs((x - px) - wexp) / wexp
                if t < best[0]:
                    best = (t, k)
            layer.append((best[0], x, best[1]))
        layers.append(layer)
        prev = layer
    best = (1e9, -1)
    for k, (pt, px, _) in enumerate(prev):
        t = pt + 1.5 * abs((x1 - px) - wexp) / wexp
        if t < best[0]:
            best = (t, k)
    if best[1] < 0:
        return [int(m) for m in mids]
    cuts, k = [], best[1]
    for layer in reversed(layers):
        if k < 0:
            return [int(m) for m in mids]
        _, x, bp = layer[k]
        cuts.append(int(x))
        k = bp
    return cuts[::-1]


def _split_line(mask, pad, chars, centers, shear_ok=True, how="dp"):
    """가로 줄 마스크를 글자 가운데(x)들을 길잡이로 자른다.

    how="dp"   잉크 적은 띠들 중에서 폭·중간 거리까지 따져 고른다(_cut_positions)
    how="mid"  이웃한 두 가운데의 중간(±10% 안에서 가장 빈 곳)에서 자른다 — CTC 밀림은 이웃끼리 상쇄돼
               중간은 꽤 정확하다. 글자 사이는 붙고 자모 사이가 빈 손글씨('파우치')는 dp 가 자모 틈에서
               자르므로, 두 벌을 다 만들어 폰트와 더 잘 맞는 쪽을 쓴다(rank_image_ex).
    """
    mask = keep_band(mask, pad)
    mask = main_band(mask)
    H = mask.shape[0]
    shear = 0.0
    if shear_ok:
        mask, shear = deshear(mask)
    off = (abs(shear) * H) / 2 + 1 if shear else 0.0   # deshear 가 오른쪽으로 민 만큼
    centers = [c + off for c in centers]
    order = np.argsort(centers)
    chars = [chars[i] for i in order]
    centers = [centers[i] for i in order]
    prof = mask.sum(axis=0).astype(float)
    ink = np.nonzero(prof)[0]
    if len(ink) == 0:
        return []
    x0, x1 = int(ink[0]), int(ink[-1]) + 1
    if how == "mid":
        mid_cuts = []
        for a, b in zip(centers, centers[1:]):
            mid, d = (a + b) / 2, max(1.0, b - a)
            l, h = int(max(x0, mid - 0.1 * d)), int(min(x1 - 1, mid + 0.1 * d))
            if h > l:
                seg = prof[l:h + 1]
                zs = np.nonzero(seg <= seg.min() + 1e-9)[0]
                mid_cuts.append(l + int(zs[len(zs) // 2]))
            else:
                mid_cuts.append(int(mid))
        cuts = [x0] + mid_cuts + [x1]
    else:
        cuts = [x0] + _cut_positions(prof, centers, H) + [x1]
    out = []
    for ch, x0, x1 in zip(chars, cuts, cuts[1:]):
        if x1 - x0 < 2:
            continue
        sub = mask[:, x0:x1]
        if tight(sub) is None:
            continue
        out.append((ch, sub))
    return out


# ── 견주기 ──────────────────────────────────────────────────────

def is_hangul(ch):
    return 0xAC00 <= ord(ch) <= 0xD7A3


def usable(ch):
    return ch.isalnum() and (is_hangul(ch) or ch.isascii())


STROKE_NORM = True     # 획 굵기를 맞춘 뒤 윤곽을 견준다(stroke_variants). 끄면 예전(9/22 아침) 방식
EXCLUDE_FID = None     # 시험용(eval_real LOO=1): 이 폰트는 후보에서 뺀다


def stroke_variants(m, height=96):
    """줄에서 자른 글자를 조금 가늘게(1~2px)·굵게(1~4px) 한 판들의 특징.

    테두리가 획 안쪽까지 파먹은 글씨는 보이는 채움이 원래보다 가늘고, 흐리거나 문턱이 낮으면
    부푼다. 96px 높이로 맞춘 뒤 바꾸므로 원본 크기에 상관없이 1px = 높이의 1%.
    가늘게 한 판은 획이 끊어져 조각이 늘거나 잉크가 4할 밑으로 줄면 버린다.
    """
    t = tight(m)
    if t is None:
        return []
    mm = t[0]
    s = height / mm.shape[0]
    mm = cv2.resize(mm.astype(np.uint8) * 255, (max(1, int(round(mm.shape[1] * s))), height),
                    interpolation=cv2.INTER_AREA) > 127
    m8 = mm.astype(np.uint8)
    n0 = ndimage.label(mm)[1]
    out = []
    for it in (1, 2):
        e = cv2.erode(m8, _CROSS, iterations=it) > 0
        if e.sum() >= 0.4 * mm.sum() and ndimage.label(e)[1] <= n0 + 1:
            g = glyph_features(e)
            if g:
                out.append(g)
    for it in (1, 2, 3, 4):
        g = glyph_features(cv2.dilate(m8, _CROSS, iterations=it) > 0)
        if g:
            out.append(g)
    return out


def clean_glyph(m, frac=0.02):
    """줄에서 자른 글자에서 잉크의 2% 도 안 되는 떨어진 티끌을 지우고, 그만큼 작은 구멍도 메운다.

    이웃 글자 테두리 부스러기·JPEG 얼룩이 글자 상자 끝에 붙으면 상자가 커져 글자 전체가 밀리고
    줄어든다(정규화가 상자 기준이라). 한글 글자는 큰 덩어리 몇 개라 2% 아래는 글자가 아니다.
    작은 구멍은 채움 무늬(긁힌 자국·빗금)나 JPEG 얼룩이다 — ㅇ·ㅁ 속은 훨씬 크다.
    """
    lab_, n = ndimage.label(m)
    if n > 1:
        sizes = ndimage.sum(m, lab_, range(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sizes >= frac * m.sum()
        m = keep[lab_]
    holes = ndimage.binary_fill_holes(m) & ~m
    lab_, n = ndimage.label(holes)
    if n:
        sizes = ndimage.sum(holes, lab_, range(1, n + 1))
        small = np.zeros(n + 1, bool)
        small[1:] = sizes < frac * m.sum()
        m = m | small[lab_]
    return m


def rank(db, glyphs, top=10, wmix=None):
    """glyphs: [(ch, 줄에서 자른 마스크)] → [(점수, 폰트id, 굵기, 이름)] 낮을수록 닮음

    글자마다 모든 굵기를 배열 한 번으로 견준다(FontDB.stack). 점수 = 글자별
    (윤곽 거리 + 겹침 + 획 굵기 차 + 장평 차)의 평균 + 줄 전체 글자 높이(탈네모) 차.
    획 굵기를 맞춘 판(stroke_variants) 중 폰트와 가장 많이 겹치는 판으로 윤곽·겹침을 잰다.
    """
    a_ch, a_st, a_as, a_tn, a_io, a_dn, a_cv, a_oh = wmix or WMIX
    q = []
    for ch, m in glyphs:
        if not usable(ch):
            continue
        m = clean_glyph(m)
        g = glyph_features(m)
        if g:
            q.append((ch, g, stroke_variants(m) if STROKE_NORM else []))
    if not q:
        return []
    nI, nq = len(db.items), len(q)
    D = np.full((nI, nq), np.inf)          # 없는 글자는 inf
    RH = np.zeros((nI, nq))

    def _cham(g, s):
        qe = np.flatnonzero(g["edge"])
        n_e = np.diff(s["eoff"])
        if len(qe):
            to_font = s["dt"][:, qe].mean(axis=1) / DT_Q                      # 내 윤곽 → 폰트 윤곽
            gdt = np.minimum(g["dt"], DT_CAP).ravel()
            to_me = np.add.reduceat(gdt[s["eidx"]], s["eoff"][:-1]) / np.maximum(1, n_e)
            cham = 0.5 * (to_font + to_me)
        else:
            cham = np.full(len(s["idx"]), 10.0)
        cham[n_e == 0] = 10.0
        return cham

    def _iou(g, s):
        qp = np.packbits(g["n"].ravel())
        inter = _POP[np.bitwise_and(s["np"], qp[None, :])].sum(axis=1, dtype=np.int32).astype(np.float32)
        return inter / np.maximum(1.0, s["nsum"] + float(g["n"].sum()) - inter)

    def _dens(g):
        return float(g["edge"].sum()) / max(1.0, float(g["n"].sum()))

    for j, (ch, g, vars_) in enumerate(q):
        s = db.stack(ch)
        ix = s["idx"]
        if not len(ix):
            continue
        cham, iou = _cham(g, s), _iou(g, s)
        dens = np.full(len(ix), _dens(g))
        if vars_:
            # 획 굵기 맞추기: 질의 글자를 조금 가늘게/굵게 한 판들 중 폰트와 가장 많이 겹치는
            # 판으로 윤곽·겹침을 잰다. 굵기 차이는 따로(a_st) 센다.
            C = np.stack([cham] + [_cham(v, s) for v in vars_])                 # (판, 굵기 수)
            I = np.stack([iou] + [_iou(v, s) for v in vars_])
            Dn = np.array([_dens(g)] + [_dens(v) for v in vars_])
            pick = I.argmax(axis=0)
            ar = np.arange(len(ix))
            cham, iou, dens = C[pick, ar], I[pick, ar], Dn[pick]
        # 윤곽 밀도(윤곽/잉크) 차 — 속 빈·3D·줄무늬 장식 폰트는 윤곽이 잉크보다 많다. 꽉 찬 글씨가
        # 그런 폰트와 '유난히' 맞는 일을 막는다(9/22 허리우드3D·히트맨 Hollow·을지로 10년후체).
        D[ix, j] = (a_ch * cham
                    + a_io * (1.0 - iou) * 10.0
                    + a_dn * np.abs(np.log(np.maximum(1e-3, dens) / np.maximum(1e-3, s["dens"])))
                    + a_cv * np.abs(g["scv"] - s["scv"])                                   # 붓 vs 펜
                    + a_oh * 0.5 * np.abs(g["oh"][None, :] - s["oh"]).sum(axis=1)          # 반듯 vs 삐뚤
                    + a_st * np.abs(g["stroke"] - s["stroke"]) / max(0.02, g["stroke"])
                    + a_as * np.abs(np.log(max(1e-3, g["aspect"]) / np.maximum(1e-3, s["aspect"]))))
        RH[ix, j] = s["h"]
    n_have = np.isfinite(D).sum(axis=1)
    ok = (n_have > 0) & (nq - n_have <= nq * 0.3)
    if any(is_hangul(ch) for ch, _, _ in q):
        ok &= ~db.is_eng
    if EXCLUDE_FID is not None:              # 시험용: 정답 폰트를 빼고 돌려 '비슷한 게 없을 때'의 점수 분포를 잰다
        ok &= np.array([it["fid"] != EXCLUDE_FID for it in db.items])
    # 가장 안 맞는 글자 4분의 1은 뺀다 — OCR 이 잘못 읽었거나 잘못 잘린 글자가
    # 한두 개 끼어도 전체 순위가 흔들리지 않게.
    Ds = np.sort(D, axis=1)
    keep = np.maximum(1, np.ceil(n_have * 0.75)).astype(int)
    csum = np.cumsum(np.where(np.isfinite(Ds), Ds, 0.0), axis=1)
    score = csum[np.arange(nI), np.clip(keep - 1, 0, nq - 1)] / keep
    if nq >= 3:
        qh = np.array([g["h"] for _, g, _ in q], float)
        qh = qh / qh.max()
        rh = RH / np.maximum(1e-9, RH.max(axis=1, keepdims=True))
        score = np.where(n_have == nq, score + a_tn * np.abs(qh[None] - rh).mean(axis=1) * 10, score)
    best = {}
    for i in np.flatnonzero(ok):
        it = db.items[i]
        key, sc = it["fid"], float(score[i])
        if key not in best or sc < best[key][0]:
            best[key] = (sc, key, it["weight"], it["name"])
    # 점수가 같으면 id 로 가른다 — 타닥타닥 id 는 글자('t123')라 문자열로 견준다
    return sorted(best.values(), key=lambda x: (x[0], str(x[1])))[:top]


# ── 외곽선·그림자가 있는 글씨 (2026-09-22) ─────────────────────────
#
# 썸네일 글씨는 채움색 + 굵은 테두리(+바깥 테두리·그림자)다. 배경색에서 먼 픽셀을 모두
# 글자로 보면(text_mask) 테두리까지 한 덩어리가 되어 획이 부풀고 모서리가 둥글어진다.
# 그래서 둥글고 굵은 엉뚱한 폰트가 닮았다고 나왔다(합성 썸네일 80장: 1위 8%·5위 안 16%).
#
# 마스크를 여러 벌 만들고, 폰트와 가장 잘 맞는 벌을 고른다.
#   전체    text_mask 그대로(테두리 없는 글씨)
#   벗김1   맨 바깥 가장자리 색(=테두리 색)과 다른 안쪽만 — 테두리 한 겹을 벗긴다
#   벗김2   벗김1을 한 번 더 — 두 겹 테두리
#   속채움  속이 빈 테두리만 잡혔을 때(채움색이 배경과 비슷할 때) 구멍을 메운 것
#   속깎기  속채움을 테두리 두께만큼 깎은 것
# 진짜 글자 모양은 어느 폰트와 거의 똑같이 맞고, 부푼 모양은 어느 폰트와도 어중간하게
# 맞는다 — 그래서 '가장 잘 맞는 폰트의 점수'가 가장 낮은 벌을 믿는다.

def _otsu(vals):
    v = np.clip(vals, 0, None)
    if v.size < 10 or v.max() <= 0:
        return None
    v8 = (v / v.max() * 255).astype(np.uint8)
    t, _ = cv2.threshold(v8.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return t / 255 * v.max()


def _clean(m, min_px):
    lab_, n = ndimage.label(m)
    if not n:
        return m
    sizes = ndimage.sum(m, lab_, range(1, n + 1))
    keep = np.zeros(n + 1, bool)
    keep[1:] = sizes >= min_px
    return keep[lab_]


def peel(mask, lab):
    """테두리 한 겹을 벗긴다. 못 벗기면(테두리가 없어 보이면) None."""
    if mask.sum() < 50:
        return None
    rim = mask & ~ndimage.binary_erosion(mask)
    if rim.sum() < 20:
        return None
    rim_col = np.median(lab[rim], axis=0)
    d = np.linalg.norm(lab - rim_col, axis=2)
    t = _otsu(d[mask])
    if t is None:
        return None
    inner = _clean(mask & (d > t), max(4, 0.002 * mask.sum()))
    if inner.sum() < 0.12 * mask.sum():
        return None
    # 벗긴 쪽은 안쪽에 있어야 한다 — 가장자리에 붙은 픽셀이 많으면 테두리가 아니다
    dt = ndimage.distance_transform_edt(mask)
    if (dt[inner] >= 1.5).mean() < 0.75:
        return None
    return inner


def hollow_fill(mask):
    """속이 빈 테두리 → (속채움, 속깎기). 구멍이 거의 없으면 None."""
    filled = ndimage.binary_fill_holes(mask)
    if filled.sum() < mask.sum() * 1.25:
        return None
    ring = ndimage.distance_transform_edt(mask)
    w = max(1, int(round(2 * np.median(ring[mask & ~ndimage.binary_erosion(mask, iterations=2)]))))
    w = max(1, int(round(np.percentile(ring[mask], 90))))
    shrunk = ndimage.binary_erosion(filled, iterations=w)
    return filled, (shrunk if shrunk.sum() > 0.2 * filled.sum() else None)


def _drop_border_blobs(m, ring=3):
    """자른 줄의 가장자리에 닿은 덩어리는 배경으로 본다(글자는 가운데 띠에 있다)."""
    lab_, n = ndimage.label(m)
    if not n:
        return m
    edge = np.zeros_like(m)
    edge[:ring] = edge[-ring:] = True
    edge[:, :ring] = edge[:, -ring:] = True
    touch = np.unique(lab_[edge & m])
    keep = np.ones(n + 1, bool)
    keep[0] = False
    keep[touch] = False
    return keep[lab_]


def _tidy(m):
    """잡티·바늘구멍 정리. 글자 속 구멍(ㅇ·ㅁ 속)은 크니 남는다."""
    m = _clean(m, max(4, 0.0008 * m.size))
    holes = ndimage.binary_fill_holes(m) & ~m
    lab_, n = ndimage.label(holes)
    if n:
        sizes = ndimage.sum(holes, lab_, range(1, n + 1))
        small = np.zeros(n + 1, bool)
        small[1:] = sizes < max(3, 0.002 * m.sum())
        m = m | small[lab_]
    return m


def color_clusters(line_rgb, k=5):
    """색으로 k 무리로 나눠, 가장자리에 닿지 않는 무리를 글자 후보로 낸다.

    사진 배경에서는 '배경색에서 먼 픽셀'이 사진 무늬까지 끌고 온다. 색 무리로 나누면
    채움색(대개 한 가지 색)이 따로 떨어져 나오고, 배경 무리는 가장자리에 닿아서 걸러진다.
    그라데이션 채움은 두 무리로 갈라질 수 있어 이웃한 두 무리를 합친 것도 낸다.
    """
    lab = cv2.cvtColor(line_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    H, W = lab.shape[:2]
    step = max(1, int(np.sqrt(H * W / 40000)))
    sample = lab[::step, ::step].reshape(-1, 3)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    cv2.setRNGSeed(0)                         # 같은 그림이면 같은 무리 — 돌릴 때마다 순위가 흔들리지 않게
    _, _, centers = cv2.kmeans(sample, k, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    d = np.linalg.norm(lab[:, :, None, :] - centers[None, None, :, :], axis=3)
    labels = d.argmin(axis=2)
    cands = []
    bg = np.zeros((H, W), bool)               # 가장자리에 닿은 덩어리들 = 배경
    raw = {}
    for c in range(k):
        raw[c] = labels == c
        m = _drop_border_blobs(raw[c])
        bg |= raw[c] & ~m
        area = m.sum()
        if area < 0.01 * H * W or area > 0.5 * H * W:
            continue
        cands.append((c, _tidy(m)))
    out = [("색%d" % c, m) for c, m in cands]
    # 이웃한 두 무리(색이 가까운 쌍)를 합친 것 — 그라데이션 채움
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            ci, cj = cands[i][0], cands[j][0]
            if np.linalg.norm(centers[ci] - centers[cj]) < 45:
                out.append(("색%d+%d" % (ci, cj), _tidy(cands[i][1] | cands[j][1])))
    # 넉넉한 판 — 무리 c 의 중심색에 '가까운' 픽셀 전부(거리에 오츠 문턱). 흰 채움 글씨는 JPEG
    # 후광 때문에 흰 무리가 둘로 갈라져(가장자리 띠 + 속) 무리 하나만 보면 고리 모양이 된다.
    wide = {}
    for c in range(k):
        t = _otsu(d[:, :, c])
        if t is None:
            continue
        m = _drop_border_blobs(d[:, :, c] < t)
        area = m.sum()
        if area < 0.01 * H * W or area > 0.5 * H * W:
            continue
        wide[c] = _tidy(m)
        out.append(("넉%d" % c, wide[c]))
    # 테두리 무리의 '속' — 테두리(한 가지 색의 고리)가 감싼 안쪽에서 배경색을 뺀 것.
    # 한 줄 안에서 글자마다 채움색이 다른 글씨(빨간 "꼭!" + 흰 "챙기는", 초록·주황 강조 낱말)는
    # 색 무리 하나로는 반쪽만 잡히지만, 테두리 고리는 하나라서 그 속을 채우면 전부 나온다.
    for c in range(k):
        for tag, ring in (("속%d" % c, raw[c]), ("넉속%d" % c, (d[:, :, c] < _otsu(d[:, :, c])) if _otsu(d[:, :, c]) else None)):
            if ring is None or ring.sum() < 0.01 * H * W:
                continue
            inner = ndimage.binary_fill_holes(ring) & ~ring & ~bg
            if inner.sum() >= max(0.3 * ring.sum(), 0.01 * H * W) and inner.sum() <= 0.6 * H * W:
                out.append((tag, _tidy(inner)))
    if len(cands) >= 2:                        # 배경이 아닌 무리 전부 — 그라데이션·여러 색 채움(테두리 없음)
        u = cands[0][1].copy()
        for _, m in cands[1:]:
            u |= m
        out.append(("색전부", _tidy(u)))
    # 거의 같은 벌은 하나만 — 견주는 값이 드니까
    uniq = []
    for name, m in out:
        if not any((m & u).sum() > 0.95 * (m | u).sum() for _, u in uniq):
            uniq.append((name, m))
    return uniq


def mask_hypotheses(line_rgb):
    lab = cv2.cvtColor(line_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    base = text_mask(line_rgb)
    out = [("전체", base)]
    p1 = peel(base, lab)
    if p1 is not None:
        out.append(("벗김1", _tidy(p1)))
        p2 = peel(p1, lab)
        if p2 is not None:
            out.append(("벗김2", _tidy(p2)))
    h = hollow_fill(base)
    if h is not None:
        out.append(("속채움", h[0]))
        if h[1] is not None:
            out.append(("속깎기", h[1]))
    out += color_clusters(line_rgb)
    return out


def rank_image(db, img, quad, char_boxes, top=10, pick="best", ocr=None, base_conf=0.0):
    """마스크 여러 벌을 견줘 결과를 준다. (결과, 1위가 나온 벌 이름) — 자세한 건 rank_image_ex

    '두드러짐' = 점수 ÷ 그 벌의 상위 30위 점수 중앙값. 부푼 덩어리는 굵은 폰트 여럿과
    고만고만하게 맞아 1위가 두드러지지 않고, 진짜 글자 모양은 한 폰트와 유난히 잘 맞는다.
    pick="mix"    1~3위는 가장 두드러진 벌 하나에서, 4위부터는 fuse 순서로(기본, 9/22 채택).
                  실제 샘플 168장 5위 안 68%·썸네일 합성 120장 81% — 두 방식의 좋은 쪽을 다 가진다.
    pick="fuse"   폰트마다 여러 벌 중 가장 좋은 두드러짐으로 줄 세운다.
                  실제 샘플 5위 안 64% → 68% 였지만 썸네일 3위 안이 76% → 73% 로 떨어졌다.
    pick="ratio"  1위 두드러짐이 가장 좋은 벌 하나의 결과만(실제 5위 안 64%).
    pick="score"  1위 점수 자체가 가장 작은 벌 하나(처음 방식).
    """
    r = rank_image_ex(db, img, quad, char_boxes, top=top, pick=pick, ocr=ocr, base_conf=base_conf)
    return r["res"], r["why"]


LINE_H = 100000  # 줄 이미지 처리 높이(px). 9/22 밤 200 으로 줄여 봤더니 테두리 글씨의 색 무리가 흐려져 마스크가
                 # 나빠졌다(호수비: 색전부 4.1 → 7.1). 시간은 어차피 견주기(_iou)가 먹어서 이득도 적었다 → 안 줄인다.


def _plausible(m, H, W):
    """마스크 벌이 글자일 가망이 있는가 — 잉크가 줄의 1~60%, 덩어리(높이 15% 넘는 것)가 둘 이상. 아니면 읽기·순위 비용을 아낀다."""
    a = m.sum()
    if a < 0.01 * H * W or a > 0.6 * H * W:
        return False
    lab_, n = ndimage.label(m)
    if n < 2:
        return False
    big = 0
    for sl in ndimage.find_objects(lab_):
        if sl[0].stop - sl[0].start >= 0.15 * H:
            big += 1
            if big >= 2:
                return True
    return False


def rank_image_ex(db, img, quad, char_boxes, top=10, pick="best", ocr=None, base_conf=0.0):
    """rank_image 의 속. dict(res, why, text, conf, masks) 를 준다.

    ocr: 줄 이미지(RGB) → (글자, 확신, [(글자, 확신, 줄 좌표 상자)]) 를 주는 함수(finder.TextFinder.recognize).
    주면 마스크 벌마다 흰 바탕에 검게 그려 다시 읽는다 —
      · 잡티·배경 덩어리 벌은 글자로 안 읽힌다(확신 ↓) → 뺀다
      · 잘 읽힌 벌은 그 글자·글자 위치로 자른다(사진에서 읽은 것보다 정확하다) → 오독도 고쳐진다
    text: 고른 벌에서 다시 읽은 글자(원래 읽은 것보다 확신이 높을 때만, 아니면 None).
    """
    line, M, pad = rectify(img, quad)
    # 속도: 줄을 높이 LINE_H(160px)로 줄여서 마스크·다시 읽기·자르기를 한다. 견주기는 어차피 48칸,
    # 활자 특징은 128px 에서 재므로 잃는 게 없다. 1440px 썸네일 제목(높이 400~600)은 이걸로 5~10배 빨라진다.
    if line.shape[0] > LINE_H:
        sc = LINE_H / line.shape[0]
        line = cv2.resize(line, (max(8, int(round(line.shape[1] * sc))), LINE_H), interpolation=cv2.INTER_AREA)
        M = np.diag([sc, sc, 1.0]).astype(np.float64) @ M
        pad = int(round(pad * sc))
    n_use0 = len([c for c, _ in char_boxes if usable(c)])
    need = max(1, n_use0 // 2)
    tried = []

    def _try(name, glyphs, text_h, conf_h, use_h):
        _rank_try(db, tried, need, top, pick, ocr, name, glyphs, text_h, conf_h, use_h)

    cands = []
    base_ink = int(text_mask(line).sum())          # '배경에서 먼 것 전부'의 잉크 — 테두리 글씨 판정에 쓴다
    for name, m in mask_hypotheses(line):
        if not _plausible(m, line.shape[0], line.shape[1]):
            continue
        text_h, conf_h, chars_h = "", 0.0, []
        if ocr is not None:
            clean = np.full(line.shape, 255, np.uint8)
            clean[m] = 0
            text_h, conf_h, chars_h = ocr(clean)
        cands.append((name, m, text_h, conf_h, chars_h))
    if ocr is not None and cands:
        cmax = max(c[3] for c in cands)
        if cmax >= 0.5:
            cands = [c for c in cands if c[3] >= 0.5 * cmax]     # 글자로 안 읽히는 벌은 순위도 안 낸다
    for name, m, text_h, conf_h, chars_h in cands:
        n_h = len([c for c in chars_h if usable(c[0])])
        # 다시 읽은 글자는 원래 읽은 것(base_conf)만큼은 확신할 때만 쓴다 — 조각난 벌은 엉뚱하게 읽힌다
        use_h = ocr is not None and conf_h >= max(0.6, base_conf - 0.1) and n_h >= max(2, 0.6 * n_use0)
        seen_cuts = set()
        for how in ("dp", "mid"):
            if use_h:
                glyphs = split_glyphs(m, M, pad, [(c[0], c[2]) for c in chars_h], line_coords=True, how=how)
            else:
                glyphs = split_glyphs(m, M, pad, char_boxes, how=how)
            sig = tuple(g.shape[1] for _, g in glyphs)
            if any(len(sig) == len(o) and all(abs(a - b) <= 4 for a, b in zip(sig, o)) for o in seen_cuts):
                continue                              # 두 방법이 거의 같은 자리(4px 안)에서 잘랐으면 한 번만
            seen_cuts.add(sig)
            _try(name if how == "dp" else name + "·중간", glyphs, text_h, conf_h, use_h)
    if not tried:
        return dict(res=[], why="", text=None, conf=0.0, tried=[])
    if ocr is not None:
        cmax = max(t["conf"] for t in tried)
        if cmax >= 0.5:
            tried = [t for t in tried if t["conf"] >= 0.5 * cmax]
    return _finish(db, tried, need, top, pick, ocr, info_extra={}, base_ink=base_ink)


def _rank_try(db, tried, need, top, pick, ocr, name, glyphs, text_h, conf_h, use_h):
    """마스크 벌 하나·자르기 하나로 순위를 내고 tried 에 넣는다."""
    if True:
        res = rank(db, glyphs, top=len(db.items) if pick in ("fuse", "mix", "best") else max(top, 30))
        if not res:
            return
        med = max(1e-6, float(np.median([r[0] for r in res[:30]])))
        ratio = res[0][0] / med
        # 벌 고르는 잣대 = 1위 점수 × 두드러짐 (÷ 다시 읽은 확신).
        # 두드러짐만 보면 고리(테두리만 잡힌 벌)·조각난 벌에서 속 빈 장식 폰트(허리우드3D·히트맨 Hollow·
        # 을지로 10년후체)가 유난히 잘 맞아 그 벌이 뽑혔다(9/22 테스트 이미지). 1위 점수를 곱하면
        # 그런 벌은 절대 점수가 나빠 밀리고, 부푼 벌(채움+테두리)은 두드러짐이 낮아 밀린다.
        if pick == "score":
            crit = res[0][0]
        elif pick == "ratio":
            crit = ratio
        else:
            crit = res[0][0] * ratio / (max(0.3, conf_h) if ocr is not None else 1.0)
        # 글자를 일부만 잡은 벌(파란 글자만, 흰 글자만)은 남은 글자가 깨끗해 점수가 좋게 나온다 — 덜 잡은 만큼 눌러 준다
        n_us = len([c for c, _ in glyphs if usable(c)])
        crit *= (max(1, need * 2) / max(1, n_us)) ** 0.7 if n_us < need * 2 else 1.0
        tried.append(dict(ok=len(glyphs) >= need, n=len(glyphs), crit=crit, res=res, name=name, med=med,
                          conf=conf_h, text=text_h if use_h else None, top1=res[0][0], ratio=ratio, glyphs=glyphs,
                          ink=int(sum(int(m.sum()) for _, m in glyphs))))


def _finish(db, tried, need, top, pick, ocr, info_extra=None, base_ink=0):
    """tried(벌별 순위)에서 벌을 고르고 결과를 만든다."""
    # 글자가 절반도 안 잘린 벌은 믿지 않는다. 모든 벌이 그러면 가장 많이 잘린 벌 중에서 고른다
    pool = [t for t in tried if t["ok"]] or [t for t in tried if t["n"] == max(x["n"] for x in tried)]
    best = min(pool, key=lambda t: t["crit"])
    info = dict(why=best["name"], text=best["text"], conf=best["conf"],
                tried=[(t["name"], t["n"], round(t["top1"], 2), round(t["ratio"], 2), round(t["conf"], 2), t["res"][0][3][:8]) for t in tried])
    if TYPO_RERANK:
        # 고른 벌이 '전체'(배경에서 먼 것 전부)보다 훨씬 작으면 테두리 글씨 — 채움만 잡은 것
        outlined = bool(base_ink > 1.3 * max(1, best["ink"]))
        # 1차 1위가 '확실히 같은 폰트'(두드러짐 ≤ 0.55, 글자당 거리 ≤ 2.2 — 정답 1위의 9할이 이 안)면 1위는 고정하고
        # 2위부터만 특징으로 다시 세운다. 안 그러면 사진 글자의 흐림·테두리로 잘못 잰 특징이 정답을 2~5위로 밀었다
        # (실제 168장 1위 83% → 75%, 9/22 밤).
        pin = bool(best["ratio"] <= PIN_RATIO and best["res"] and best["res"][0][0] <= PIN_SCORE)
        best["res"], info["explain"] = rerank_typo(db, best["glyphs"], best["res"], outlined=outlined, pin_first=pin)
        info["pinned"] = pin
        info["outlined"] = outlined
    if pick not in ("fuse", "mix"):
        return dict(res=best["res"][:top], **_gate(best["res"][:top], best["ratio"], db), **info)
    # 합치기: 폰트마다 여러 벌 중 가장 좋은 '두드러짐'(점수 ÷ 그 벌 상위 30위 중앙값)으로 줄 세운다.
    # 1위는 ratio 와 같고, 고른 벌이 틀렸어도 다른 벌에서 두드러진 폰트가 2~5위에 들어온다.
    # 단, 고른 벌보다 잣대가 1.5배 넘게 나쁜 벌은 섞지 않는다 — 고리·조각 벌의 장식 폰트가 4~5위로 새어 든다.
    fused, abs_min = {}, {}
    for t in [t for t in pool if t["crit"] <= 1.5 * best["crit"]]:
        for sc, fid, w, nm in t["res"]:
            v = sc / t["med"]
            if fid not in fused or v < fused[fid][0]:
                fused[fid] = (v, fid, w, nm)
            if fid not in abs_min or sc < abs_min[fid]:
                abs_min[fid] = sc
    out = sorted(fused.values(), key=lambda x: (x[0], str(x[1])))
    if pick == "mix":
        # 1~3위는 가장 두드러진 벌 하나에서, 그 뒤는 합친 순서에서
        head = [(r[0] / best["med"],) + tuple(r[1:]) for r in best["res"][:3]]
        seen = {r[1] for r in head}
        out = head + [r for r in out if r[1] not in seen]
    # 결과의 점수는 절대 점수(가장 좋은 벌에서의 글자당 거리)로 — 문턱(_gate)을 대려면 줄마다 같은 자여야 한다
    out = [(abs_min.get(r[1], r[0] * best["med"]),) + tuple(r[1:]) for r in out[:top]]
    return dict(res=out, **_gate(out, best["ratio"], db), **info)


# ── 활자 특징으로 다시 줄 세우기 (2026-09-22 밤) ──────────────────────
# 사용자님: "잉크량으로만 보는 거 아니야? 이미지 속 글자의 특징을 잡아서 골라 줘야지." 윤곽 거리·겹침은 큰 모양만
# 보므로 각진/둥근 모서리, 부리, 가로세로 대비, 손글씨의 들쭉날쭉함을 못 가른다. 그래서 1차 순위 상위 TYPO_K 개를
# typo.features(굵기·대비·모서리·획 끝)와 줄 규칙성(높이·폭·밑선 흔들림)의 차이로 다시 세운다.
TYPO_RERANK = __import__("os").environ.get("TYPO_RERANK", "1") == "1"
TYPO_K = 40
# 특징 차이의 무게: (굵기, 대비, 모서리, 획 끝, 규칙성). 단위: 굵기 0.05·대비 log0.2·모서리 0.06·끝 0.15·규칙성 0.1 당 1
TYPO_W = tuple(float(x) for x in __import__("os").environ.get("TYPO_W", "0.3,0.4,0.5,0.4,0.5").split(","))


def _typo_of_glyphs(masks):
    """글자 마스크들 → (중앙값 특징 dict, 규칙성 3값). 특징을 못 잰 글자는 뺀다."""
    import typo
    fs = [typo.features(clean_glyph(m)) for m in masks]
    fs = [f for f in fs if f]
    if not fs:
        return None, typo.line_regularity(masks)
    med = {k: float(np.median([f[k] for f in fs])) for k in ("w", "contrast", "corner", "terminal")}
    med["corner_ok"] = med["w"] >= 0.08          # 가는 글씨는 모서리·끝을 못 믿는다
    return med, typo.line_regularity(masks)


def _typo_dist(q, rq, f, rf):
    """두 특징 묶음의 거리(항목별) — dict. 모서리는 굵기로 눌러 견준다(굵을수록 같은 각도에서도 값이 크다)."""
    a_w, a_c, a_k, a_t, a_r = TYPO_W
    d = dict(w=abs(q["w"] - f["w"]) / 0.05,
             contrast=abs(math.log(max(0.2, q["contrast"]) / max(0.2, f["contrast"]))) / 0.2,
             reg=sum(abs(x - y) for x, y in zip(rq, rf)) / 0.1)
    if q["corner_ok"] and f["corner_ok"]:
        d["corner"] = abs(q["corner"] * 0.15 / q["w"] - f["corner"] * 0.15 / f["w"]) / 0.06
        d["terminal"] = abs(q["terminal"] - f["terminal"]) / 0.15
    else:
        d["corner"] = d["terminal"] = 0.0
    for k_ in ("w", "contrast", "corner", "terminal", "reg"):
        d[k_] = min(2.0, d[k_])                    # 항목 하나가 2를 넘지 않게 — 흐림·테두리로 잘못 잰 항목이 순위를 뒤집지 않게
    d["total"] = a_w * d["w"] + a_c * d["contrast"] + a_k * d["corner"] + a_t * d["terminal"] + a_r * d["reg"]
    return d


PIN_RATIO, PIN_SCORE = 0.65, 2.8    # (예전 규칙: 1위만 고정) 0.55·2.2 로 실제 168장 1위 79%, 0.65·2.8 로 81%
PIN_ABS = 2.2                        # 모양 점수 이 안이면 '거의 같은 폰트' 무리 — 1차 순서 유지, 그 뒤만 재정렬


def rerank_typo(db, glyphs, res, k=None, outlined=False, pin_first=False):
    """res(1차 순위, 절대 점수)의 상위 k 개를 활자 특징 차이를 더한 점수로 다시 세운다. (새 res, 설명 dict)
    outlined: 테두리 글씨(채움만 잡은 벌) — 테두리가 채움의 모서리·끝을 깎아 둥글고 밋밋하게 보이므로 그 둘은 안 잰다."""
    k = k or TYPO_K
    chars = [ch for ch, _ in glyphs if usable(ch)]
    masks = [m for ch, m in glyphs if usable(ch)]
    q, rq = _typo_of_glyphs(masks)
    if q is None or len(chars) < 2:
        return res, {}
    if outlined:
        q["corner_ok"] = False
    face_of = {(it["fid"], it["weight"]): i for i, it in enumerate(db.items)}
    head, explain = [], {}
    for sc, fid, w, nm in res[:k]:
        i = face_of.get((fid, w))
        if i is None:
            head.append((sc, fid, w, nm))
            continue
        fs, hs, ws, bs = [], [], [], []
        for ch in chars:
            memo = db.typo_memo.get((i, ch))
            if memo is None:
                g = db.glyph(i, ch)
                if g is None:
                    db.typo_memo[(i, ch)] = False
                    continue
                img = Image.new("L", (RS * 3, RS * 2), 0)
                ImageDraw.Draw(img).text((RS // 2, RS * 3 // 2), ch, font=db.font(i), fill=255, anchor="ls")
                import typo as _typo
                tf_ = _typo.features(np.asarray(img) > 127)
                memo = dict(f=tf_, h=g["h"], w=g["w"], b=g["bottom"] * RS)
                db.typo_memo[(i, ch)] = memo
            if memo is False:
                continue
            if memo["f"]:
                fs.append(memo["f"])
            hs.append(memo["h"]); ws.append(memo["w"]); bs.append(memo["b"])
        if fs:
            f = {k: float(np.median([x[k] for x in fs])) for k in ("w", "contrast", "corner", "terminal")}
            f["corner_ok"] = f["w"] >= 0.08
        else:
            f = None
        if f is None or len(hs) < 2:
            head.append((sc, fid, w, nm))
            continue
        hs, ws, bs = np.array(hs, float), np.array(ws, float), np.array(bs, float)
        # 규칙성은 글자 3개부터(2개면 둘 다 0 으로 두어 항이 죽는다 — typo.line_regularity 와 같은 규칙)
        rf = (float(hs.std() / hs.mean()), float(ws.std() / ws.mean()), float(bs.std() / hs.mean())) if len(hs) >= 3 else (0.0, 0.0, 0.0)
        d = _typo_dist(q, rq, f, rf)
        # 이미지 글자가 손글씨처럼 들쭉날쭉(높이·폭·밑선 흔들림 합 0.3 이상)한데 후보가 활자 갈래(고딕·명조·디스플레이)면
        # 1.0 을 더한다 — 9/22 사용자님: "는여기서마무리는 손글씨인데 명조들이 나왔군"
        hand_q = sum(rq) >= 0.3
        cats = db.cats.get(fid, set())
        if hand_q and cats and not (cats & {"손글씨", "캘리"}):
            d["total"] += 1.0
            d["hand"] = True
        head.append((sc + d["total"], fid, w, nm, sc))
        explain[fid] = dict(d=d, q=q, f=f, rq=rq, rf=rf, shape=sc)
    # 모양 점수가 PIN_ABS(2.2, 정답 1위의 9할이 이 안) 이하인 후보는 '거의 같은 폰트'로 보고 1차 순서 그대로 앞에 둔다.
    # 나머지(대체 폰트 후보)만 특징으로 다시 세운다. 사용자님 테스트 줄들은 모양 점수 2.5~5 라 전부 재정렬된다.
    keep = [x for x in head if x[4] <= PIN_ABS] if len(head) and len(head[0]) == 5 else ([head[0]] if pin_first and head else [])
    rest = [x for x in head if not any(x is y for y in keep)]
    rest.sort(key=lambda x: (x[0], str(x[1])))
    head = keep + rest
    # 순서는 특징을 더한 점수로, 결과에 적는 점수는 1차(모양) 점수 — 문턱(_gate)은 모양 점수로 잰다
    head = [(x[4], x[1], x[2], x[3]) if len(x) == 5 else x for x in head]
    return head + list(res[k:]), explain


def explain_text(ex):
    """설명 dict → 사람이 읽을 한 줄: 무엇이 비슷하고 무엇이 다른지."""
    if not ex:
        return ""
    d, q, f, rq, rf = ex["d"], ex["q"], ex["f"], ex["rq"], ex["rf"]
    out = []
    out.append("굵기 " + ("비슷" if d["w"] < 1 else ("더 굵음" if f["w"] > q["w"] else "더 가늚")))
    if d["contrast"] >= 1.2:
        out.append("가로획 " + ("더 가늚" if f["contrast"] < q["contrast"] else "더 굵음"))
    if q["corner_ok"] and f["corner_ok"]:
        qk, fk = q["corner"] * 0.15 / q["w"], f["corner"] * 0.15 / f["w"]
        out.append("모서리 " + ("비슷" if d["corner"] < 1 else ("더 각짐" if fk > qk else "더 둥긂")))
        if d["terminal"] >= 1.2:
            out.append("획 끝 " + ("살이 더 붙음" if f["terminal"] > q["terminal"] else "더 밋밋함"))
    sq, sf = sum(rq), sum(rf)
    if d["reg"] >= 1.5:
        out.append("글자 크기·밑선이 " + ("더 들쭉날쭉" if sf > sq else "더 반듯"))
    if d.get("hand"):
        out.append("손글씨 느낌인데 활자체")
    return " · ".join(out)


# '비슷한 폰트가 없다' 문턱(2026-09-22 사용자님: "우리가 가진 폰트 중에 비슷한 게 없으면 안 보여 주고, 없다고 하자").
# 폰트픽 실제 샘플 168장(정답 앎)으로 잰 분포 —
#   1위 점수(글자당 거리): 1위가 정답이면 중앙 0.98·90% 2.17, 오답이면 중앙 3.29·25% 1.59
#   두드러짐(1위 ÷ 상위 30위 중앙값): 정답이면 중앙 0.36·90% 0.62, 오답이면 중앙 0.78·25% 0.70
# 점수 2.5 & 두드러짐 0.7 이면 정답 1위의 9할이 통과하고 오답 1위는 2할쯤 남는다. 사용자님이 "비슷한 게
# 없다"고 짚은 줄들(호수비 3.0·곤약젤리 3.4·반면·무기자차)은 전부 문턱 밖.
# 9/22 사용자님 테스트 이미지에서 "비슷한 게 없다"고 짚은 반면(2.39)·무기자차(2.24)가 2.5 는 통과해서 2.2 로 내림
# (정답 1위의 9할이 남는다). 괜찮다고 본 줄들은 0.6~1.6.
# 9/22 저녁 사용자님: "똑같은 폰트를 찾는 게 아니라 유료 폰트를 무료·타닥타닥으로 대체할 비슷한 폰트를 찾는 게
# 목표 — 기준이 너무 타이트하다(무기자차·공유·파우치 털기는 얼추 비슷한 게 있을 것)". 그래서
#   · 점수 문턱은 4.0 — 정답이 있을 때 99%, 정답을 뺐을 때도 9할이 통과(정말 못 잡은 것만 '없음')
#   · 두드러짐 문턱은 뺌 — 일반 고딕은 비슷한 게 많아 두드러지지 않는데 그게 곧 대체 폰트가 많다는 뜻
#   · 대신 목록은 1위와 같은 갈래(손글씨/고딕/명조/디스플레이/캘리)만, 1위 점수의 1.5배 안까지만
# 9/22 밤: 손글씨·테두리 글씨는 마스크가 조금만 거칠어도 4~5점이 나온다(파우치 털기는 4.7) — 사용자님은 그래도
# 손글씨 후보를 보고 싶어 하신다. 5.0 이면 정답을 뺀 판(LOO)에서도 95%가 통과, 못 잡은 것(4번 이미지 5.8)만 '없음'.
NONE_ABOVE = float(__import__("os").environ.get("NONE_ABOVE", "5.0"))     # 1위 점수가 이보다 크면 없음
NONE_RATIO = float(__import__("os").environ.get("NONE_RATIO", "9"))       # 두드러짐 문턱(9 = 안 씀)
CAND_REL = float(__import__("os").environ.get("CAND_REL", "1.5"))         # 후보는 1위 점수의 1.5배 안까지만
MIN_SHOW = 3                                                                # 그래도 같은 갈래에서 3개는 보여 준다


def _gate(res, ratio=None, db=None):
    """res: [(절대 점수, fid, w, 이름)] → dict(shown=문턱 안의 후보, verdict='ok'|'none', best_score, ratio)"""
    if not res:
        return dict(shown=[], verdict="none", best_score=None, ratio=ratio)
    best = float(res[0][0])
    none = best > NONE_ABOVE or (ratio is not None and ratio > NONE_RATIO)
    cats0 = db.cats.get(res[0][1], set()) if db is not None else set()
    shown, fill = [], []
    for r in ([] if none else res):
        if r[0] > NONE_ABOVE:
            continue
        c = db.cats.get(r[1], set()) if db is not None else set()
        if cats0 and c and not (cats0 & c):
            continue                                   # 1위와 갈래가 다르면 뺀다
        (shown if r[0] <= CAND_REL * best else fill).append(r)
    # 1위가 아주 잘 맞으면 1.5배 안에 드는 게 없다 — 그래도 대체 폰트를 고를 수 있게 같은 갈래에서 3개는 채운다
    shown = shown + fill[:max(0, MIN_SHOW - len(shown))]
    return dict(shown=shown, verdict="ok" if shown else "none", best_score=best, ratio=ratio)
