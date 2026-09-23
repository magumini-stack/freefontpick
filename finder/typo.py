"""글자 마스크에서 활자 특징을 잰다 — 굵기 대비·모서리·획 끝(부리)·규칙성.

2026-09-22 사용자님: "잉크량으로만 보는 거 아니야? 이미지 속 글자의 특징을 잡아서 골라 줘야지."
  · 호수비 진다운 씨 → 비트로코어(각지고 무거운 고딕)가 맞고 창원단감아삭체(둥근 덩어리)는 전혀 다르다
  · 반면·많이 남아있는 → 살짝 부리가 있는 고딕인데 읏맨체(강한 부리)·퓨전굴림(둥근 굴림)·투혼경남체가 나왔다
  · 파우치 털기는 → 반듯한 펜 손글씨인데 TDTD트윙클(들쭉날쭉 귀여운 손글씨)이 나왔다
윤곽 거리·겹침은 큰 모양만 보고 이런 차이를 못 본다. 그래서 글자마다 아래를 따로 잰다.

  w         획 굵기(높이 대비)                         — 뼈대 위 거리변환의 중앙값 ×2
  contrast  가로획 굵기 / 세로획 굵기                    — 명조 0.4~0.7, 고딕 ~1
  corner    모서리 날카로움 = 열기·닫기(반지름 0.5w)로 잃고 얻는 잉크 비율 — 둥근 굴림은 작고 각진 고딕은 크다
  terminal  획 끝 살(부리·꺾임) = 뼈대 끝점 둘레(반지름 w) 잉크 / w²   — 둥근 끝 ~1.3, 잘린 끝 ~1.5, 부리 1.8~

높이 128px 로 맞춰 재므로 원본 크기와 무관하다. 사진 글씨는 흐려서 모서리가 조금 둥글게 재지고 테두리가 획을
파먹으면 끝이 가늘게 재진다 — 굵은 글씨(굵기 8px 이상)에서만 모서리·끝을 믿는다(rank 에서 가중).
"""
import cv2
import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize

H0 = 128
_K8 = np.ones((3, 3), np.uint8)


def prep(m, h=H0):
    """마스크를 높이 h 로(비율 유지). 이미 잘라낸(tight) 마스크를 준다고 본다."""
    ys, xs = np.flatnonzero(m.any(axis=1)), np.flatnonzero(m.any(axis=0))
    if not len(xs):
        return None
    m = m[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1]
    s = h / m.shape[0]
    mm = cv2.resize(m.astype(np.uint8) * 255, (max(2, int(round(m.shape[1] * s))), h), interpolation=cv2.INTER_AREA) > 127
    return np.pad(mm, 4)


def _disk(r):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def features(m):
    """m: 글자 마스크 → dict(w, contrast, corner, terminal) 또는 None(너무 작음)."""
    mm = prep(m)
    if mm is None or mm.sum() < 30:
        return None
    u8 = mm.astype(np.uint8)
    dt = cv2.distanceTransform(u8, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    sk = skeletonize(mm)
    thick = 2.0 * dt[sk]
    if len(thick) < 8:
        return None
    w = float(np.median(thick))
    # ── 방향별 굵기(대비): 뼈대 그림의 구조 텐서로 뼈대 방향을 잰다
    S = cv2.GaussianBlur(sk.astype(np.float32), (0, 0), 1.0)
    gx = cv2.Sobel(S, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(S, cv2.CV_32F, 0, 1, ksize=3)
    j11 = cv2.GaussianBlur(gx * gx, (0, 0), 2.0)
    j22 = cv2.GaussianBlur(gy * gy, (0, 0), 2.0)
    j12 = cv2.GaussianBlur(gx * gy, (0, 0), 2.0)
    coh = np.sqrt((j11 - j22) ** 2 + 4 * j12 ** 2) / np.maximum(1e-6, j11 + j22)     # 한 방향으로 곧은 정도
    theta = 0.5 * np.arctan2(2 * j12, j11 - j22)                                        # 기울기(가장자리) 방향
    # 기울기가 세로(±90°)면 뼈대는 가로획, 기울기가 가로(0°)면 세로획
    ang = np.abs(theta[sk])
    good = coh[sk] > 0.6
    horiz = good & (ang > np.deg2rad(65))
    vert = good & (ang < np.deg2rad(25))
    if horiz.sum() >= 6 and vert.sum() >= 6:
        contrast = float(np.median(thick[horiz]) / max(1e-6, np.median(thick[vert])))
    else:
        contrast = 1.0
    # ── 모서리: 반지름 0.4w 원으로 열고 닫아서 잃고 얻는 잉크
    r = max(1, int(round(0.5 * w)))     # JPEG 흐림(1~2px)보다 훨씬 큰 반지름 — 둥근 모서리(반지름 ≥ r)만 잉크를 안 잃는다
    k = _disk(r)
    opened = cv2.morphologyEx(u8, cv2.MORPH_OPEN, k)
    closed = cv2.morphologyEx(u8, cv2.MORPH_CLOSE, k)
    area = float(u8.sum())
    corner = float((area - opened.sum()) / area + (closed.sum() - area) / area)
    # ── 획 끝: 뼈대 끝점(8-이웃이 하나) 둘레 반지름 w 안의 잉크 / w²
    nb = cv2.filter2D(sk.astype(np.uint8), -1, _K8, borderType=cv2.BORDER_CONSTANT) - sk.astype(np.uint8)
    ends = np.argwhere(sk & (nb == 1))
    R = max(2, int(round(w)))
    vals = []
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    disk = (yy ** 2 + xx ** 2) <= R * R
    for y, x in ends:
        if 2 * dt[y, x] < 0.5 * w or 2 * dt[y, x] > 1.6 * w:
            continue                       # 실오라기·덩어리 끝은 뺀다
        y0, y1 = max(0, y - R), min(mm.shape[0], y + R + 1)
        x0, x1 = max(0, x - R), min(mm.shape[1], x + R + 1)
        sub = mm[y0:y1, x0:x1]
        d = disk[(y0 - (y - R)):(y1 - (y - R)), (x0 - (x - R)):(x1 - (x - R))]
        vals.append(float((sub & d).sum()) / max(1.0, w * w))
    terminal = float(np.median(vals)) if len(vals) >= 2 else 1.5
    return dict(w=w / H0, contrast=contrast, corner=corner, terminal=terminal, n_end=len(vals))


def line_regularity(glyph_masks):
    """줄에서 자른 글자 마스크들 → (높이 흔들림, 폭 흔들림, 밑선 흔들림) — 손글씨는 크고 활자체는 0 에 가깝다.
    글자 마스크는 줄 높이 그대로(잘라내지 않은) 것을 준다 — 밑선은 잉크의 맨 아래 y."""
    hs, ws, bs = [], [], []
    for m in glyph_masks:
        ys, xs = np.flatnonzero(m.any(axis=1)), np.flatnonzero(m.any(axis=0))
        if not len(xs):
            continue
        hs.append(ys[-1] - ys[0] + 1)
        ws.append(xs[-1] - xs[0] + 1)
        bs.append(ys[-1])
    if len(hs) < 3:
        return (0.0, 0.0, 0.0)
    hs, ws, bs = np.array(hs, float), np.array(ws, float), np.array(bs, float)
    return (float(hs.std() / hs.mean()), float(ws.std() / ws.mean()), float(bs.std() / hs.mean()))
