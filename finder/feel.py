"""폰트 느낌 벡터(2단계) — 추론. 학습은 feel_train.py, 자료는 feel_data.py.

글자 마스크(줄 높이 그대로 자른 것) → feel_glyph 64×64 → models/feel.onnx → 128차원 단위벡터 → 줄 평균.
굵기마다 기준 벡터 = 깨끗하게 그린 REF_CHARS 글자들의 벡터 평균. 두 벡터의 코사인이 클수록 '느낌'이 가깝다.
기준 벡터는 목록 폴더의 feel_refs.npz 에 굵기(파일 키·굵기)별로 저장해 두고, 없는 것만 새로 만든다.
"""
import hashlib
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("FEEL_MODEL") or os.path.join(HERE, "models", "feel.onnx")
S, BOX = 64, 56
REF_CHARS = "가나다라마바사아자차카타파하글씨폰트한국사랑오늘우리행복"
_sess = None


def available():
    return os.path.exists(MODEL)


def feel_glyph(m):
    """글자 마스크 → 64×64 uint8(0/1), 잉크를 56 상자에 비율 유지로. 비면 None. (feel_data 와 같은 함수)"""
    ys, xs = np.flatnonzero(m.any(axis=1)), np.flatnonzero(m.any(axis=0))
    if len(xs) < 2 or len(ys) < 2:
        return None
    g = m[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1].astype(np.float32)
    s = BOX / max(g.shape)
    w, h = max(1, int(round(g.shape[1] * s))), max(1, int(round(g.shape[0] * s)))
    g = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR) > 0.5
    out = np.zeros((S, S), np.uint8)
    y0, x0 = (S - h) // 2, (S - w) // 2
    out[y0:y0 + h, x0:x0 + w] = g
    return out


def _load():
    global _sess
    if _sess is None:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(os.environ.get("FEEL_THREADS", "2"))
        so.log_severity_level = 3
        _sess = ort.InferenceSession(MODEL, so, providers=["CPUExecutionProvider"])
    return _sess


def embed_glyphs(gs):
    """64×64 글자들 → 줄 벡터(단위). 글자가 없으면 None."""
    gs = [g for g in gs if g is not None and g.sum() >= 12]
    if not gs:
        return None
    x = np.stack(gs)[:, None].astype(np.float32)
    e = _load().run(["e"], {"x": x})[0]
    v = e.mean(0)
    return (v / max(1e-6, float(np.linalg.norm(v)))).astype(np.float32)


def embed(masks):
    return embed_glyphs([feel_glyph(m) for m in masks])


def _model_tag():
    st = os.stat(MODEL)
    return hashlib.md5(("%d:%d" % (st.st_size, int(st.st_mtime))).encode()).hexdigest()[:8]


def ref_glyphs(font, has):
    """굵기의 기준 글자 마스크들(깨끗하게 그린 것)."""
    from PIL import Image, ImageDraw
    f = font.font_variant(size=96)
    out = []
    for ch in REF_CHARS:
        if not has(ch):
            continue
        img = Image.new("L", (192, 192), 0)
        ImageDraw.Draw(img).text((48, 140), ch, font=f, fill=255, anchor="ls")
        g = feel_glyph(np.asarray(img) > 127)
        if g is not None and g.sum() >= 12:
            out.append(g)
    return out


def refs(db, log=None):
    """db.items 순서의 기준 벡터 (n, 128) — 목록 폴더 feel_refs.npz 에 모델별로 캐시. 못 만든 굵기는 0 벡터."""
    cache = getattr(db, "_feel_refs", None)
    if cache is not None:
        return cache
    tag = _model_tag()
    path = os.path.join(os.path.dirname(os.path.dirname(db.stack_dir)),
                        "feel_refs_%s.npz" % os.path.splitext(os.path.basename(MODEL))[0])
    have = {}
    if os.path.exists(path):
        z = np.load(path, allow_pickle=False)
        if str(z["tag"]) == tag:
            have = dict(zip(z["keys"].tolist(), z["vecs"]))
    out = np.zeros((len(db.items), 128), np.float32)
    dirty = 0
    for i, it in enumerate(db.items):
        key = "%s|%d" % (it["fn_key"], it["weight"])
        v = have.get(key)
        if v is None:
            # db.font() 의 폰트 목록(LRU)은 요청 처리와 같이 쓰면 안 된다 — 서버는 이걸 뒤 스레드에서 돌린다. 따로 연다.
            font = db._load(it["fn"])
            v = embed_glyphs(ref_glyphs(font, lambda ch, i=i: db.has(i, ch))) if font is not None else None
            v = np.zeros(128, np.float32) if v is None else v
            have[key] = v
            dirty += 1
            if log and dirty % 100 == 0:
                log("  느낌 기준 %d개 새로 만듦" % dirty)
        out[i] = v
    if dirty:
        keys = list(have.keys())
        np.savez(path, tag=np.array(tag), keys=np.array(keys), vecs=np.stack([have[k] for k in keys]))
    db._feel_refs = out
    return out
