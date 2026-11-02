"""글줄 '눈'(③, 2026-10-19) — 추론. 학습은 font3/train.py·train3.py, 자료는 font3/data.py·data3.py.

질의: 엔진이 떼어 낸 글자 띠들을 이어 붙인 줄 → 엔진 자르기와 같은 손질(큰 줄만·이탤릭 세우기·티끌) → 잉크 높이 44
(전체 64) → 너비 256 창(짧으면 가운데, 길면 128 간격 여러 창의 평균) → models/eye.onnx → 128차원 단위벡터.
후보: **같은 글자를 그 폰트로 그린 줄**(같은 손질) — 글자가 같으니 글자 모양 차이 대신 폰트 차이만 남는다.
두 벡터의 코사인이 클수록 같은(비슷한) 폰트. 질의 줄 벡터·후보 줄 벡터는 (굵기, 글자) 별로 잠깐 기억해 둔다.

눈이 둘(2026-11-02):
  main = models/eye.onnx      새 눈 2 — 사진 결과 순서. 새 눈 3 은 사용자님 사진 판단 131줄에서 오히려 낮았다
                              (흉내 규칙 1위 비슷 50% → 42~44%, 정답 맞히기는 비슷).
  sim  = models/eye_sim.onnx  새 눈 3 섞은 판(8번째 저장본과 끝 저장본의 가중치 평균) — '이 느낌으로 더 보기'의 기준 줄·같은
                              글자 견주기와 사진 ㅎ·ㅊ 꼭지 머리. 폰트끼리 판단 120개 1위 비슷 59→66%(고딕 69→79%·손글씨 58→66%),
                              고딕 꼭지 같은 이웃 69→80%, 사진 꼭지 22줄 규칙 75% → 머리 95%.
  sim 파일이 없으면 main 하나로 다 한다(예전 그대로).
"""
import collections
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("EYE_MODEL") or os.path.join(HERE, "models", "eye.onnx")
SIM_MODEL = os.environ.get("EYE_SIM_MODEL") or os.path.join(HERE, "models", "eye_sim.onnx")
# 크기 판(2026-11-02 새 눈 3): 모델 옆 '<모델>.json'(export.py 가 씀)의 geom — g64 = eye2(잉크 44·창 256),
# g128 = eye3(잉크 88·창 512, 후보를 160px 로 그린다). 파일이 없으면 g64.
GEOMS = {"g64": (64, 44, 10, 256, 1024, 96), "g128": (128, 88, 20, 512, 2048, 160)}
CACHE_MAX = 4000
SPACE_ABS, SPACE_REL = 0.30, 0.15
# ── 폰트끼리 닮음('이 느낌으로 더 보기', 2026-10-21) ───────────────────────────
# 굵기마다 기준 문장들을 깨끗하게 그린 줄의 벡터 평균 — 사진이 아니라 폰트끼리 견주므로 훨씬 고르다.
# 서버는 뜰 때 뒤에서 만들고(처음 한 번 몇 분) 목록 폴더 eye_refs_<태그>[_lat].npz 에 남긴다(feel.refs 와 같은 방식).
KO_REFS = ["가나다라마바사", "아자차카타파하", "폰트 찾기 한글", "오늘도 우리 행복", "사랑 글씨 좋은 날"]
LAT_REFS = ["ABDEGHKMNRS", "abdeghkmnprst", "Hamburgefonts", "Sale 2026"]


def _despeck(m):
    from scipy import ndimage
    lab, n = ndimage.label(m)
    if n <= 1:
        return m
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    keep = np.zeros(n + 1, bool)
    keep[1:] = sizes >= max(3, 0.003 * sizes.sum())
    return keep[lab]


def _repr(m, E):
    m = E.main_band(m)
    m, _ = E.deshear(m)
    return _despeck(m)


def _join(glyphs):
    """[(글자, 줄 높이 띠 마스크)] → (이어 붙인 줄, [(글자, 시작 x, 끝 x)]) 또는 (None, []).
    세로쓰기는 글자마다 높이가 다르다 — 가운데 맞춤."""
    gs = [(ch, np.asarray(m, bool)) for ch, m in glyphs if m is not None and np.asarray(m).size]
    if not gs:
        return None, []
    hh = max(m.shape[0] for _, m in gs)
    cols, spans, x = [], [], 0
    for ch, m in gs:
        if m.shape[0] != hh:
            p = np.zeros((hh, m.shape[1]), bool)
            o = (hh - m.shape[0]) // 2
            p[o:o + m.shape[0]] = m
            m = p
        cols.append(m)
        spans.append((ch, x, x + m.shape[1]))
        x += m.shape[1]
    return np.concatenate(cols, axis=1), spans


def query_text(glyphs, text=None):
    """후보 폰트로 그릴 글자 — 떼어 낸 글자에 **사진 속 띄어쓰기를 되살려** 붙인다.

    다시 읽은 글자는 띄어쓰기를 자주 빠뜨린다(정답 시험: 띄어쓰기 있는 줄 334 중 다시 읽은 글자에 남은 것 130).
    그러면 질의 줄에는 낱말 사이 틈이 있는데 후보는 붙여 그려 견주게 되어, 원래 자간이 넓은 폰트가 유리해졌다.
    그래서 글자 띠 사이 빈틈(잉크 높이로 나눔)이 SPACE_ABS(0.30)를 넘거나 그 줄의 보통 틈(중앙값)보다 SPACE_REL(0.15)
    넘게 크면 띄어쓰기로 본다 — 정답 시험에서 한글 띄어쓰기 97% 찾음·보통 틈 2% 잘못, 영문 100%·0%."""
    chars = "".join(ch for ch, _ in glyphs)
    ms = [np.asarray(m, bool) for _, m in glyphs]
    if len(ms) < 2 or any(m.shape[0] != ms[0].shape[0] for m in ms):
        return chars                          # 세로쓰기 등 — 띄어쓰기를 따지지 않는다
    rows = np.flatnonzero(np.concatenate(ms, axis=1).any(axis=1))
    if not len(rows):
        return chars
    hgt = float(rows[-1] - rows[0] + 1)
    x, edges = 0, []
    for m in ms:
        cols = np.flatnonzero(m.any(axis=0))
        edges.append((x + cols[0], x + cols[-1]) if len(cols) else (x, x))
        x += m.shape[1]
    gaps = np.array([(edges[i + 1][0] - edges[i][1]) / hgt for i in range(len(edges) - 1)])
    med = float(np.median(gaps))
    out = ""
    for i, (ch, _) in enumerate(glyphs):
        out += ch
        if i < len(gaps) and (gaps[i] > SPACE_ABS or gaps[i] - med > SPACE_REL):
            out += " "
    return out


class Eye:
    """눈 하나 — 모델 파일, 그 옆 '<모델>.json'(크기 판·꼭지 머리), 세션, 후보 벡터 기억."""

    def __init__(self, path):
        self.path = path
        try:
            import json
            with open(path + ".json", encoding="utf-8") as f:
                self.side = json.load(f)
        except Exception:
            self.side = {}
        self.geom = self.side.get("geom", "g64")
        self.H, self.INNER, self.TOP, self.WIN, self.MAXW, self.RS = GEOMS.get(self.geom, GEOMS["g64"])
        self._sess = None
        self._cache = collections.OrderedDict()          # (굵기 키, 글자) → 벡터

    def available(self):
        return os.path.exists(self.path)

    def _load(self):
        if self._sess is None:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = int(os.environ.get("EYE_THREADS", "2"))
            so.log_severity_level = 3
            self._sess = ort.InferenceSession(self.path, so, providers=["CPUExecutionProvider"])
        return self._sess

    def line_input(self, m):
        """줄 마스크(bool) → (H×MAXW uint8 0/1, 쓴 너비). 비면 (None, 0)."""
        H, INNER, TOP, MAXW = self.H, self.INNER, self.TOP, self.MAXW
        ys, xs = np.flatnonzero(m.any(axis=1)), np.flatnonzero(m.any(axis=0))
        if len(xs) < 2 or len(ys) < 2:
            return None, 0
        g = m[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1].astype(np.float32)
        s = INNER / g.shape[0]
        w = max(1, int(round(g.shape[1] * s)))
        if w > 4 * MAXW:
            g = g[:, :int(4 * MAXW / s)]
            w = max(1, int(round(g.shape[1] * s)))
        g = cv2.resize(g, (w, INNER), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR) > 0.5
        out = np.zeros((H, MAXW), np.uint8)
        w = min(w, MAXW)
        out[TOP:TOP + INNER, :w] = g[:, :w]
        return out, w

    def _windows(self, arr, w):
        H, WIN = self.H, self.WIN
        if w <= WIN:
            out = np.zeros((H, WIN), np.uint8)
            o = (WIN - w) // 2
            out[:, o:o + w] = arr[:, :w]
            return [out]
        st = list(range(0, w - WIN + 1, WIN // 2))
        if st[-1] != w - WIN:
            st.append(w - WIN)
        return [arr[:, s:s + WIN] for s in st]

    def _embed(self, items):
        """[(arr, w)] → (n, 128) 단위벡터."""
        ws, own = [], []
        for k, (arr, w) in enumerate(items):
            for x in self._windows(arr, w):
                ws.append(x); own.append(k)
        out = np.zeros((len(items), 128), np.float32)
        sess = self._load()
        for a in range(0, len(ws), 32):
            x = np.stack(ws[a:a + 32])[:, None].astype(np.float32)
            np.add.at(out, np.array(own[a:a + 32]), sess.run(["e"], {"x": x})[0])
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)

    def _draw(self, font, t, E):
        """폰트로 글자 t 를 깨끗하게 그린 줄 → (arr, w)."""
        from PIL import Image, ImageDraw
        RS = self.RS
        f = font.font_variant(size=RS)
        bb = f.getbbox(t)
        img = Image.new("L", (max(8, int(bb[2] - bb[0] + 0.8 * RS) + 4), int(RS * 2.2)), 0)
        ImageDraw.Draw(img).text((0.4 * RS - bb[0], RS * 1.5), t, font=f, fill=255, anchor="ls")
        return self.line_input(_repr(np.asarray(img) > 127, E))

    def query_vec(self, glyphs, E):
        """엔진이 떼어 낸 글자 [(글자, 줄 높이 띠 마스크)] → 줄 벡터 또는 None."""
        line, _ = _join(glyphs)
        if line is None:
            return None
        arr, w = self.line_input(_repr(line, E))
        return None if arr is None else self._embed([(arr, w)])[0]

    def cand_vecs(self, db, faces, text, E):
        """후보 굵기들 → {굵기: 같은 글자로 그린 줄의 벡터}. 질의 글자의 절반 넘게 없는 굵기는 뺀다."""
        need = max(1, len(text.replace(" ", "")) // 2)
        out, todo, items = {}, [], []
        for i in faces:
            key = (db.face_keys[i] if hasattr(db, "face_keys") else str(i), text)
            v = self._cache.get(key)
            if v is not None:
                self._cache.move_to_end(key)
                out[i] = v
                continue
            t2 = "".join(c for c in text if c == " " or db.has(i, c)).strip()
            if len(t2.replace(" ", "")) < need:
                continue
            font = db.font(i)
            if font is None:
                continue
            try:
                arr, w = self._draw(font, t2, E)
            except Exception:
                continue
            if arr is not None:
                todo.append((i, key)); items.append((arr, w))
        if items:
            for (i, key), v in zip(todo, self._embed(items)):
                out[i] = v
                self._cache[key] = v
            while len(self._cache) > CACHE_MAX:
                self._cache.popitem(last=False)
        return out

    def kk_prob(self, glyphs, E):
        """사진 글자 [(글자, 줄 높이 띠 마스크)] → ([그 글자들], 꼭지가 서 있을 확률) 또는 None(꼭지 머리 없음·ㅎ·ㅊ 없음).
        새 눈 3 의 꼭지 머리(export.py 가 모델 옆 json 의 kk 에 W·b 로 남김) — 학습처럼 초성 ㅎ 이 있으면 ㅎ 글자들, 없으면 ㅊ
        글자들 가운데에 창을 놓고 창 벡터 → 머리 로짓 평균. 사진 글자를 잘못 떼어 규칙(design.py)이 못 잴 때도 잰다."""
        kk = self.side.get("kk")
        if not kk or not glyphs:
            return None
        import design as D
        cho = {ch: (D.parts(ch) or (None,))[0] for ch, _ in glyphs}
        want = 18 if 18 in cho.values() else (14 if 14 in cho.values() else None)
        if want is None:
            return None
        line, spans = _join(glyphs)
        if line is None:
            return None
        rep = _repr(line, E)
        xs, ys = np.flatnonzero(rep.any(axis=0)), np.flatnonzero(rep.any(axis=1))
        if len(xs) < 2 or len(ys) < 2:
            return None
        s = self.INNER / (ys[-1] - ys[0] + 1)
        arr, w = self.line_input(rep)
        if arr is None:
            return None
        H, WIN = self.H, self.WIN
        wins, chars = [], []
        for ch, a, b in spans:
            if cho.get(ch) != want:
                continue
            chars.append(ch)
            c = int(round(((a + b) / 2 - xs[0]) * s))
            st = int(np.clip(c - WIN // 2, 0, max(0, w - WIN)))
            win = np.zeros((H, WIN), np.uint8)
            seg = arr[:, st:min(w, st + WIN)]
            o = (WIN - seg.shape[1]) // 2 if w < WIN else 0
            win[:, o:o + seg.shape[1]] = seg
            wins.append(win)
        if not wins:
            return None
        e = self._load().run(["e"], {"x": np.stack(wins)[:, None].astype(np.float32)})[0]
        lg = (e @ np.asarray(kk["W"], np.float32).T + np.asarray(kk["b"], np.float32)).mean(0)
        lg = lg - lg.max()
        return list(dict.fromkeys(chars)), float(np.exp(lg[1]) / np.exp(lg).sum())

    def _model_tag(self):
        import hashlib
        st = os.stat(self.path)
        return hashlib.md5(("%d:%d" % (st.st_size, int(st.st_mtime))).encode()).hexdigest()[:8]

    def _ref_items(self, font, has, texts, E):
        out = []
        for t in texts:
            t2 = "".join(c for c in t if c == " " or has(c)).strip()
            if len(t2.replace(" ", "")) < 4:
                continue
            arr, w = self._draw(font, t2, E)
            if arr is not None:
                out.append((arr, w))
        return out

    def refs(self, db, E, script="ko", log=None):
        """db.items 순서의 기준 벡터 (n, 128) — 목록 폴더 eye_refs_<태그>[_lat].npz 에 캐시. 못 만든 굵기는 0 벡터.
        폰트는 db._load 로 따로 연다(뒤 스레드에서 돌려도 찾기 요청의 폰트 목록(LRU)과 엉키지 않게)."""
        attr = "_eye_refs" if script == "ko" else "_eye_refs_lat"
        cache = getattr(db, attr, None)
        if cache is not None:
            return cache
        texts = KO_REFS if script == "ko" else LAT_REFS
        tag = self._model_tag()
        path = os.path.join(os.path.dirname(os.path.dirname(db.stack_dir)), "eye_refs_%s%s.npz" % (tag, "" if script == "ko" else "_lat"))
        have = {}
        if os.path.exists(path):
            z = np.load(path, allow_pickle=False)
            have = dict(zip(z["keys"].tolist(), z["vecs"]))
        out = np.zeros((len(db.items), 128), np.float32)
        dirty = 0
        excluded = getattr(db, "excluded", None)
        for i, it in enumerate(db.items):
            if excluded is not None and excluded[i]:
                continue
            key = "%s|%d" % (it["fn_key"], it["weight"])
            v = have.get(key)
            if v is None:
                font = db._load(it["fn"])
                items = self._ref_items(font, lambda ch, i=i: db.has(i, ch), texts, E) if font is not None else []
                v = self._embed(items).mean(0) if items else np.zeros(128, np.float32)
                n = float(np.linalg.norm(v))
                v = (v / n if n > 0 else v).astype(np.float32)
                have[key] = v
                dirty += 1
                if log and dirty % 200 == 0:
                    log("  새 눈 기준(%s) %d개 새로 만듦" % (script, dirty))
                if dirty % 500 == 0:                       # 오래 걸리니 중간중간 남긴다(서버가 도중에 다시 떠도 이어서)
                    keys = list(have.keys())
                    np.savez(path, keys=np.array(keys), vecs=np.stack([have[k] for k in keys]))
            out[i] = v
        if dirty:
            keys = list(have.keys())
            np.savez(path, keys=np.array(keys), vecs=np.stack([have[k] for k in keys]))
        setattr(db, attr, out)
        return out


main = Eye(MODEL)
sim = Eye(SIM_MODEL) if os.path.exists(SIM_MODEL) else main

# 예전 이름 그대로(엔진·서비스·실험실 도구가 부르는 곳): 사진 결과는 main, '더 보기' 기준 벡터·꼭지 머리는 sim
available = main.available
query_vec = main.query_vec
cand_vecs = main.cand_vecs
line_input = main.line_input
kk_prob = sim.kk_prob
refs = sim.refs
