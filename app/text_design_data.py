"""텍스트 디자인(/text-design) 페이지의 폰트 자료를 요청 때 DB 에서 만든다 (2026-10-22).

사용자님 "새 폰트를 업데이트할 때마다 디자인 모달 연결을 배포를 통해서 해야 해?" → "서버에서 자동으로 넣게 바꿔줘".
예전에는 시안 폴더(Desktop\\projects\\폰트픽\\글자이미지_시안)의 build.py 가 그날의 폰트 목록을 페이지에 박아 두어,
그 뒤 등록한 폰트는 배포 전까지 목록에 없었다. 이제 라우트(app/routers/text_design.py)가 이 모듈로 만든 값으로
페이지 속 두 자리를 갈아 끼운다(publish.py 가 /*FFP_FONTS*/…/*FFP_FONTS_END*/·/*FFP_USES*/…/*FFP_USES_END*/ 로 감싸 둔다).
여기서 실패하면 페이지에 박혀 있던 값이 그대로 나간다.

만드는 것
- 폰트 목록 [id, 이름, 파일 판, 처음 쓸 곳] — 파일이 있는 폰트 전부, sort_order 순.
  '처음 쓸 곳'은 상세페이지 '이 폰트로 디자인하기' 모달이 처음 여는 쓸 곳(10/21 사용자님 "서체 모양에 따라서").
- 쓸 곳마다 '폰트 더보기' 50종 — 용도 허브에 올라 있는 순서 → 허브 태그 폰트 → 허브 기준 점수 순, 추천 꾸밈에 쓴 폰트는 꼭 넣는다.

허브 기준 점수는 10/15 허브 다시 매기기(Desktop\\projects\\폰트픽\\허브순위_2026-10-15\\rank.py)의 다섯 쓸 곳 함수를 옮긴 것이다
(시안 폴더 font_use.py 와 같은 규칙). 모양 갈래·실측값(metric_x·w·d)·굵기·쓰임 라이선스(meta.license.perms)로 매긴다.
그려진 한글 수는 DB 에 없어 rank.py 의 coverage.json(10/15 실측)을 app/hangul_coverage.json 으로 옮겨 쓴다(10/22 에 #145 교체·#771·#772 를 더함).
여기 없는 폰트(그 뒤 등록)는 rank.py 처럼 '다 그려짐'으로 본다 — 새로 재면 그 파일에 더할 것.
"""
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from . import content_cache
from .models import Font, UseCase

SLUGS = ["thumbnail", "vlog", "quote", "goods", "product"]   # 페이지 쓸 곳 순서(0 썸네일 … 4 상세페이지)
FONT_N = 50

# 허브 기준에 하나도 안 걸리면(실측값이 아직 없는 새 폰트·라이선스로 빠진 폰트) 모양 갈래만으로
BY_SHAPE = {
    "캘리그라피": 2, "부드러운 명조": 2, "독특한 세리프": 2,
    "손글씨": 1,
    "펜시": 3, "장식": 3, "디스플레이": 3, "제목용 굴림": 3,
    "제목-본문용 고딕": 4, "네모틀 고딕": 0,
}
SHAPES = ["제목-본문용 고딕", "네모틀 고딕", "디스플레이", "제목용 굴림", "장식", "독특한 세리프", "부드러운 명조",
          "손글씨", "펜시", "캘리그라피", "디자인 영어", "디자이너 필수 영문"]
COMMERCE = ["위메프", "11번가", "롯데마트", "롯데쇼핑", "G마켓", "지마켓", "이랜드", "쿠팡", "우아한형제들", "티몬", "카페24", "Cafe24",
            "무신사", "29CM", "SSG", "신세계", "컬리", "오늘의집", "GS리테일", "NHN커머스", "인터파크", "옥션", "현대백화점", "애터미", "망고보드"]


def _feat(font: Font, weights: list) -> dict:
    m = font.meta or {}
    tags = [t.name for t in font.tags]
    ws = sorted(weights)
    nw = len(ws) or int(re.sub(r"\D", "", font.weights or "1") or 1)
    lic = m.get("license") if isinstance(m.get("license"), dict) else {}
    return {
        "id": font.id, "name": font.name, "maker": font.maker or "", "tags": tags,
        "shape": next((t for t in tags if t in SHAPES), ""),
        "mood": m.get("mood") or [], "usage": m.get("usage") or [], "summary": m.get("summary") or "",
        "en": bool(font.is_english), "x": font.metric_x, "w": font.metric_w, "d": font.metric_d,
        "nw": nw, "maxw": max(ws) if ws else 400, "perms": lic.get("perms") or {},
    }


def _ok(p, *keys, strict=False):
    allow = ("y",) if strict else ("y", "c")
    return all(p.get(k) in allow for k in keys)


def _pen(p, *keys):
    return 0.15 * sum(1 for k in keys if p.get(k) == "c")


def _bold(f):
    d = f["d"] or 0
    if f["maxw"] >= 800 and f["nw"] >= 3:
        d += 0.14
    elif f["maxw"] >= 700 and f["nw"] >= 2:
        d += 0.09
    return d


try:
    COV = {int(k): v for k, v in json.loads((Path(__file__).resolve().parent / "hangul_coverage.json").read_text(encoding="utf-8")).items()}
except Exception:
    COV = {}


def _cov(f):
    """rank.py full_cov — 한글 11,172자면 1, 2,780자 판 0.6, 2,350자 판 0.35, 그보다 적으면 0. 모르면 1."""
    c = COV.get(f["id"])
    return 1.0 if c is None else (1.0 if c >= 11000 else 0.6 if c >= 2700 else 0.35 if c >= 2300 else 0.0)


def s_thumbnail(f):
    if f["en"] or f["shape"] in ("부드러운 명조", "캘리그라피", "디자인 영어", "디자이너 필수 영문"):
        return None
    if not _ok(f["perms"], "web", "video") or f["x"] is None:
        return None
    b = _bold(f)
    if b < 0.42 or f["x"] < 0.82:
        return None
    s = 1.2 * b + 0.9 * f["x"] + 0.25 * min(f["w"] or 0, 1.0)
    s += 0.12 * any(u in f["usage"] for u in ("썸네일", "제목"))
    s += 0.25 * _cov(f) - _pen(f["perms"], "web", "video")
    s -= 0.15 * (f["shape"] == "장식")
    return s


def s_vlog(f):
    if f["en"] or f["shape"] not in ("손글씨", "제목용 굴림", "제목-본문용 고딕", "펜시", "네모틀 고딕"):
        return None
    if not _ok(f["perms"], "video", "web") or f["x"] is None or f["d"] is None or f["w"] is None:
        return None
    d, w = f["d"], f["w"]
    if d < 0.17 or d > 0.55 or w > 1.0 or f["x"] < 0.55:
        return None
    s = 1.4 * (1.0 - w) + (1.0 - abs(d - 0.32) * 3) * 0.6 + 0.6 * min(f["x"], 0.95)
    s += 0.2 * ("영상자막" in f["usage"]) + 0.1 * any(m in f["mood"] for m in ("친근한", "따뜻한", "부드러운"))
    s += 0.5 * _cov(f) - _pen(f["perms"], "video", "web")
    return s


def s_quote(f):
    if f["en"] or f["shape"] not in ("손글씨", "캘리그라피", "부드러운 명조", "독특한 세리프"):
        return None
    if f["shape"] in ("부드러운 명조", "독특한 세리프") and re.search(r"돋움|고딕", f["name"]):
        return None
    if not _ok(f["perms"], "print", "web") or f["d"] is None:
        return None
    s = 0.6 * sum(m in f["mood"] for m in ("감성적", "따뜻한", "부드러운", "꿈같은", "고급스러운"))
    s += 0.25 * any(u in f["usage"] for u in ("캐치프레이즈", "SNS카드", "포스터"))
    s += 0.5 * (1.0 - abs(f["d"] - 0.24) * 3)
    s += 0.35 * _cov(f) - _pen(f["perms"], "print", "web")
    return s


def s_goods(f):
    if f["en"] or f["shape"] not in ("디스플레이", "제목용 굴림", "펜시", "장식", "손글씨"):
        return None
    if not _ok(f["perms"], "package", "print", strict=True) or f["d"] is None:
        return None
    b = _bold(f)
    if b < 0.4:
        return None
    s = 1.3 * b + 0.3 * any(m in f["mood"] for m in ("장난스러운", "친근한", "독특한"))
    s += 0.2 * ("패키지" in f["usage"]) + 0.15 * ("귀여운" in f["tags"]) + 0.25 * _cov(f)
    return s


def s_product(f):
    if f["en"] or f["shape"] not in ("제목-본문용 고딕", "네모틀 고딕", "디스플레이", "제목용 굴림"):
        return None
    if not _ok(f["perms"], "web", strict=True) or f["nw"] < 2:
        return None
    com = any(c.lower() in f["maker"].lower() for c in COMMERCE)
    s = 0.9 * com + 0.4 * min(f["nw"], 6) / 6 + 0.25 * (f["maxw"] >= 700) + 0.4 * _cov(f)
    s += 0.15 * any(u in f["usage"] for u in ("썸네일", "제목", "캐치프레이즈", "정보전달"))
    return s


SCORERS = [s_thumbnail, s_vlog, s_quote, s_goods, s_product]


def _english_use(f):
    """영문 폰트 — 세리프·필기체는 감성, 굵은 제목체는 썸네일, 나머지는 상세페이지(rank.py g_english 를 줄인 것)."""
    n, t = f["name"], f["name"] + " " + f["summary"]
    if re.search(r"Serif|Garamond|Baskerville|Playfair|Merriweather|Lora|Bodoni|Fraunces|Cinzel|Petrona|Bona", n) and "Sans" not in n:
        return 2
    if re.search(r"Pacifico|Caveat|Dancing|Vibes|Sacramento|Lobster|Kaushan|Amatic|Marker|Shadows|Miama|August|Gabrielle|Chancery", n) \
            or re.search(r"필기|손글씨", f["summary"]):
        return 2
    if re.search(r"Bebas|Oswald|Anton|Archivo Black|Bungee|Alfa Slab|Righteous|Lilita|Abril|BANGERS|좁|압축|Condensed|제목체", t):
        return 0
    if re.search(r"세리프", f["summary"]) and "산세리프" not in f["summary"]:
        return 2
    return 4


def _build(db: Session) -> dict:
    from .routers.files import _merged_weights, file_version_of

    fonts = (db.query(Font).filter(Font.has_file.is_(True)).order_by(Font.sort_order, Font.id).all())
    feats = []
    for font in fonts:
        try:
            ws = [w["weight"] for w in _merged_weights(font)]
        except Exception:
            ws = []
        feats.append(_feat(font, ws))

    # 쓸 곳마다 점수 순위 → 그 폰트가 위에서 몇 % 에 서나
    scored, pct = [], {}
    for k, fn in enumerate(SCORERS):
        sc = sorted(((s, f["id"]) for f in feats if (s := fn(f)) is not None), key=lambda t: -t[0])
        scored.append([i for _, i in sc])
        for r, (_, i) in enumerate(sc):
            pct.setdefault(i, [None] * len(SCORERS))[k] = r / max(1, len(sc) - 1)

    def first_use(f):
        p = pct.get(f["id"])
        if p and any(v is not None for v in p):
            return min((v, k) for k, v in enumerate(p) if v is not None)[1]
        if f["en"]:
            return _english_use(f)
        return BY_SHAPE.get(f["shape"], 0)

    out_fonts = [[f["id"], f["name"], file_version_of(f["id"]), first_use(f)] for f in feats]

    have = {f["id"] for f in feats}
    hub_order = {}
    for k, slug in enumerate(SLUGS):
        order = []
        uc = db.query(UseCase).filter(UseCase.slug == slug).first()
        if uc:
            order += [x.font_id for x in uc.fonts if x.font is not None]
            if uc.tag is not None:
                order += [ft.id for ft in sorted(uc.tag.fonts, key=lambda ft: (ft.sort_order or 0, ft.id))]
        order += scored[k]
        seen, ids = set(), []
        for i in order:
            if i in have and i not in seen:
                seen.add(i)
                ids.append(i)
        hub_order[slug] = ids[:FONT_N]
    return {"fonts": out_fonts, "hub": hub_order}


def data(db: Session) -> dict:
    return content_cache.get("text_design:data", ttl=1800, build=lambda: _build(db))


_FONTS_RE = re.compile(r"/\*FFP_FONTS\*/.*?/\*FFP_FONTS_END\*/", re.S)
_USES_RE = re.compile(r"/\*FFP_USES\*/(.*?)/\*FFP_USES_END\*/", re.S)


def inject(html: str, db: Session) -> str:
    """페이지에 박힌 폰트 목록·쓸 곳 폰트 목록을 지금 DB 값으로 갈아 끼운다. 자리가 없거나 실패하면 그대로 둔다."""
    m = _USES_RE.search(html)
    if not m or not _FONTS_RE.search(html):
        return html
    d = data(db)
    have = {f[0] for f in d["fonts"]}
    uses = json.loads(m.group(1))
    for u in uses:
        ids = [i for i in (d["hub"].get(u.get("slug")) or u.get("fonts") or []) if i in have]
        # 목록에 없는 폰트 번호가 섞이면 페이지 스크립트가 이름을 못 찾아 멈춘다 — 지금 있는 폰트만
        recipe_fonts = [r["font"] for r in u.get("recipes", []) if r["font"] in have]
        # 추천 꾸밈에 쓴 폰트가 50 안에 없으면 끝자리를 내주고 넣는다(꾸밈을 눌렀을 때 목록에 그 폰트가 보이게) — build.py 와 같게
        for rf in recipe_fonts:
            if rf not in ids:
                drop = next((i for i in reversed(ids) if i not in recipe_fonts), None)
                if drop is None or len(ids) < FONT_N:
                    ids.append(rf)
                else:
                    ids[ids.index(drop)] = rf
        u["fonts"] = ids
    dump = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = _FONTS_RE.sub(lambda _: "/*FFP_FONTS*/" + dump(d["fonts"]) + "/*FFP_FONTS_END*/", html, count=1)
    html = _USES_RE.sub(lambda _: "/*FFP_USES*/" + dump(uses) + "/*FFP_USES_END*/", html, count=1)
    return html
