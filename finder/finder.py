"""글자 줄 찾기 + 읽기 (운영에서도 그대로 쓸 조각).

RapidOCR 의 글자 영역 찾기(det)는 그대로 쓰면 큰 제목 글씨를 통째로 놓친다(2026-09-22 사용자님
테스트 이미지 10장 중 5장). 원인 둘:
  1. RapidOCR 이 짧은 변이 736px 이 안 되는 이미지를 736 으로 **키운다**(limit_type=min).
     썸네일은 대개 1440×400 쯤이라 글씨가 두 배로 커져 모델이 글자로 안 본다.
  2. 모델은 글자 높이가 20~80px 쯤일 때 잘 찾는다. 200px 짜리 제목은 글자 속 구멍(ㅇ)만 잡는다.
그래서 키우기를 끄고(limit_type=max) 이미지를 여러 배율로 줄여 가며 찾은 뒤 합친다.
합칠 때는 잘게 찾은 상자들이 큰 상자를 6할 넘게 덮으면 큰 상자를 버리고(윗줄·아랫줄이 한 상자로
붙은 것), 아니면 큰 상자를 살리고 그 안의 조각들을 버린다(글자 속 구멍).
"""
import numpy as np
import cv2
import os

import engine_v0 as E

SCALES = (1.0, 0.66, 0.5, 0.33, 0.25)


def _aabb(q):
    q = np.asarray(q, float)
    return q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()


def _inter(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _area(a):
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


class TextFinder:
    # rapidocr 3.9.2 가 내려받는 모델 파일 이름 — FINDER_MODELS 폴더에 이 셋이 있으면 그것을 쓴다
    MODEL_FILES = {"Det": "ch_PP-OCRv5_det_mobile.onnx", "Rec": "korean_PP-OCRv5_rec_mobile.onnx",
                   "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx"}

    def __init__(self, log_level="error", model_dir=None):
        from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType
        params = {
            "Global.log_level": log_level,
            "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
            "Det.limit_type": "max", "Det.limit_side_len": 1600,
            "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE,
            "Rec.lang_type": LangRec.KOREAN,
            "Global.return_word_box": True, "Global.return_single_char_box": True,
            "Global.text_score": 0.0,        # 못 읽은 줄도 상자는 남긴다 — 글자는 사용자가 고칠 수 있다
        }
        # 모델 파일을 직접 준다(서버는 /data/models — rapidocr 의 내려받기 서버 modelscope.cn 을 안 탄다).
        # 폴더가 없거나 파일이 빠지면 예전처럼 rapidocr 가 처음 쓸 때 내려받는다(실험실).
        model_dir = model_dir or os.environ.get("FINDER_MODELS")
        if model_dir:
            paths = {k: os.path.join(model_dir, v) for k, v in self.MODEL_FILES.items()}
            if all(os.path.exists(x) for x in paths.values()):
                for k, x in paths.items():
                    params[k + ".model_path"] = x
        self.eng = RapidOCR(params=params)

    # ── 줄 찾기 ──────────────────────────────────────────────────
    def detect(self, img, scales=SCALES, box_thresh=0.4, unclip_ratio=1.8):
        """img(RGB) → [(사각형 4점, 점수, 배율)] 큰 글씨부터."""
        H, W = img.shape[:2]
        per_scale = []
        for s in scales:
            sw, sh = int(round(W * s)), int(round(H * s))
            if max(sw, sh) < 64:
                continue
            small = img if s == 1.0 else cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
            pad = int(0.1 * max(sw, sh))
            padded = cv2.copyMakeBorder(small, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
            r = self.eng(padded, use_det=True, use_rec=False, use_cls=False,
                         box_thresh=box_thresh, unclip_ratio=unclip_ratio)
            boxes = []
            if r.boxes is not None:
                for b, sc in zip(r.boxes, r.scores):
                    q = (np.asarray(b, float) - pad) / s
                    q[:, 0] = np.clip(q[:, 0], 0, W - 1)
                    q[:, 1] = np.clip(q[:, 1], 0, H - 1)
                    a = _aabb(q)
                    if a[2] - a[0] < 12 or a[3] - a[1] < 12:
                        continue
                    boxes.append((q, float(sc), s))
            per_scale.append(boxes)
        return self._merge(per_scale)

    @staticmethod
    def _merge(per_scale):
        """배율마다 찾은 상자를 다 모은다(겹침 정리는 find_lines 가 읽은 결과로 한다)."""
        return [b for bs in per_scale for b in bs]

    def find_lines(self, img, scales=SCALES):
        """img(RGB) → [dict(quad, det, scale, text, conf, chars)] 큰 줄부터.

        배율마다 찾은 상자를 전부 읽어 본 뒤, 겹치는 상자끼리 묶고 묶음마다 '가장 잘 읽힌 배율'의
        상자만 남긴다. 잘 읽힌 정도 = Σ(읽은 글자 수 × 확신). 윗줄·아랫줄이 한 상자로 붙으면
        읽기가 흐트러지고(확신 ↓), 글자 속 구멍 같은 조각은 글자가 안 나온다(0). 굵게 줄인 배율의
        상자가 좀 헐거워도 통째로 잘 읽히면 그쪽이 이긴다. 글자 높이로 고르면 큰 제목 옆의
        작은 글씨가 같은 묶음에 끼어 배율을 잘못 고르는 일이 있었다(2026-09-22).
        """
        boxes = self.detect(img, scales=scales)
        rows = []
        for q, sc, s in boxes:
            r = self.read_line(img, q)
            n_use = len([c for c in r["chars"] if E.usable(c[0])])
            rows.append(dict(quad=np.asarray(q).tolist(), det=float(sc), scale=float(s), text=r["text"],
                             conf=float(r["conf"]), chars=r["chars"], _n=n_use))
        n = len(rows)
        if not n:
            return []
        ab = [_aabb(r["quad"]) for r in rows]
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(n):
            for j in range(i + 1, n):
                if _inter(ab[i], ab[j]) > 0.5 * min(_area(ab[i]), _area(ab[j])):
                    parent[find(i)] = find(j)
        groups = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        out = []
        for members in groups.values():
            by_scale = {}
            for i in members:
                by_scale.setdefault(rows[i]["scale"], []).append(i)

            def goodness(s):
                return sum(rows[i]["_n"] * rows[i]["conf"] for i in by_scale[s] if rows[i]["conf"] >= 0.3)

            best = max(by_scale, key=lambda s: (round(goodness(s), 3), s))   # 같으면 덜 줄인 쪽
            chosen = by_scale[best]
            out += [rows[i] for i in chosen]
            for i in members:                        # 고른 배율에는 없는 줄이면 살린다
                if rows[i]["scale"] != best and rows[i]["conf"] >= 0.3 and all(
                        _inter(ab[i], ab[j]) < 0.3 * min(_area(ab[i]), _area(ab[j])) for j in chosen):
                    out.append(rows[i])
        for r in out:
            r.pop("_n", None)
        out.sort(key=lambda r: -(_aabb(r["quad"])[3] - _aabb(r["quad"])[1]))
        return out

    # ── 읽기 ────────────────────────────────────────────────────
    def recognize(self, line_rgb):
        """곧게 편 한 줄 이미지 → (글자, 평균 확신, [(글자, 확신, 줄 안 상자)])"""
        r = self.eng(line_rgb, use_det=False, use_cls=False, use_rec=True,
                     return_word_box=True, return_single_char_box=True)
        if not r.txts or not r.txts[0]:
            return "", 0.0, []
        H, W = line_rgb.shape[:2]
        chars = []
        # 읽기만 시키면 글자 상자를 안 주고 CTC 열 번호(word_cols)만 준다. 열 하나 = 폭 W/line_txt_len.
        info = r.word_results[0] if r.word_results else None
        if info is not None and getattr(info, "word_cols", None):
            cols = [c for w in info.word_cols for c in w]
            chs = [c for w in info.words for c in w]
            confs = list(info.confs) if info.confs else [float(r.scores[0])] * len(chs)
            n = max(1.0, float(info.line_txt_len))
            for ch, col, conf in zip(chs, cols, confs):
                x = (col + 0.5) * W / n
                hw = max(1.0, 0.5 * W / n)
                chars.append((ch, float(conf), [[x - hw, 0.0], [x + hw, 0.0], [x + hw, float(H)], [x - hw, float(H)]]))
        text = r.txts[0]
        return text, float(r.scores[0]), chars

    def read_line(self, img, quad):
        """원본 이미지의 사각형 하나 → 곧게 편 줄 + 읽은 글자 + 원본 좌표 글자 상자."""
        line, M, pad = E.rectify(img, quad)
        text, conf, chars = self.recognize(line)
        Minv = np.linalg.inv(M)
        out = []
        for ch, c, box in chars:
            pts = cv2.perspectiveTransform(np.array([box], np.float32), Minv.astype(np.float32))[0]
            out.append((ch, c, pts.tolist()))
        return dict(line=line, M=M, pad=pad, text=text, conf=conf, chars=out)
