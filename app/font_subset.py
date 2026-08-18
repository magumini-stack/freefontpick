"""갤러리 미리보기용 서브셋 폰트.

왜 만드나
---------
메인 갤러리는 카드마다 그 폰트로 문구 한 줄을 그린다. 그런데 한글 폰트는
한 벌이 평균 476KB(최대 2.4MB)라, 첫 화면 30장이면 14MB가 흐른다.
카드가 실제로 그리는 글자는 몇 백 자뿐인데 1만 3천 자를 통째로 받는 셈이다.

그래서 **화면에 나올 수 있는 글자만 담은 작은 파일**을 따로 만든다.
실측으로 원본의 9~32%(대개 20% 안팎)까지 줄어든다.

어떻게 쓰나 — unicode-range
---------------------------
같은 패밀리 이름으로 face를 두 벌 건다. 원본을 먼저, 서브셋을 나중에.

    @font-face{font-family:'FFP-101'; src:url(...file);}
    @font-face{font-family:'FFP-101'; src:url(...subset); unicode-range:U+AC00,...;}

브라우저가 글자마다 알아서 고른다. 아래 글자 집합 안에 있으면 서브셋만 받고,
사용자가 목록 밖 글자를 직접 치면 그때 원본을 받는다. **벗어나기 전까지
원본은 아예 안 받는다.** 구글 폰트가 한글을 쪼갤 때 쓰는 방식과 같다.

선언 순서가 중요하다 — 서브셋을 나중에 둬야 겹치는 글자에서 서브셋이 이긴다.

글자 집합
---------
서버가 이미 가진 문구 우물에서 모은다. 갤러리의 400개 문구도 이 우물에서
가져온 것이라(static/index.html 주석 참조) 따로 셀 필요가 없다 — 실측으로
갤러리 문구가 새로 더하는 글자는 0자였다.

폰트 이름은 넣지 않는다. 카드에서 이름은 UI 글꼴로 그리고 미리보기 문구만
그 폰트로 그린다. 이름을 넣으면 폰트가 하나 늘 때마다 209개를 다시 만들어야
한다.

빠져도 깨지지 않는다
--------------------
집합에 없는 글자는 브라우저가 원본 face로 넘어가 그린다. 서브셋 파일이 아직
없으면 프론트가 face를 아예 안 걸고 원본만 쓴다(has_subset). 어느 쪽이든
화면이 깨지지 않고 느려질 뿐이다.
"""
import hashlib
import os
import threading
import time
from pathlib import Path

SUBSETS_DIR = Path(os.getenv("SUBSETS_DIR", "/app/user_data/subsets"))
try:
    SUBSETS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass


def _collect_chars() -> set:
    """서버가 아는 모든 문구에서 글자를 모은다."""
    chars = set()

    def walk(o):
        if isinstance(o, str):
            chars.update(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    try:
        from .pairing_phrases import THEME_PHRASE_BANK
        walk(THEME_PHRASE_BANK)
    except Exception:
        pass
    try:
        from .pair_specimens import PAIR_CATEGORIES
        for c in PAIR_CATEGORIES:
            walk([c.get("ko"), c.get("en"), c.get("label"), c.get("desc")])
    except Exception:
        pass

    # 아스키 전체 + 한글 자모 + 자주 쓰는 기호
    chars.update(chr(c) for c in range(0x20, 0x7F))
    chars.update(chr(c) for c in range(0x3131, 0x3164))
    chars.update("　·…‘’“”—–₩※○●△▲□■♥★☆→←↑↓")

    # 사이트가 늘 쓰는 말. 문구 뱅크에는 '폰트'·'픽' 같은 글자가 없어서
    # 따로 넣는다 — 사용자가 미리보기에 가장 먼저 쳐 보는 말이기도 하다.
    chars.update(
        "폰트픽 무료 상업용 다운로드 미리보기 조합 찾기 검색 굵기 제목 본문 "
        "서브타이틀 갤러리 추천 인기 최신 전체 카테고리 태그 라이선스 제작사 "
        "배포 저작권 사용 가능 범위 문의 안내 이름 크기 자간 줄간격 새로고침 "
        "디자인 손글씨 고딕 명조 바탕 장식 영문 한글 숫자 기호 굵게 얇게 "
        "월화수목금토일 년월일시분초 가나다라마바사아자차카타파하"
    )
    return chars


SUBSET_CHARS = frozenset(_collect_chars())

# 글자 집합이 바뀌면 이 값이 바뀌고, 캐시 파일 이름이 달라져 자동으로 다시 만든다.
CHARSET_VERSION = hashlib.md5(
    "".join(sorted(SUBSET_CHARS)).encode("utf-8")
).hexdigest()[:8]


def _unicode_range() -> str:
    """CSS unicode-range 문자열. 이어지는 코드포인트는 범위로 접는다."""
    cps = sorted(ord(c) for c in SUBSET_CHARS)
    out, a, b = [], cps[0], cps[0]
    for c in cps[1:]:
        if c == b + 1:
            b = c
        else:
            out.append((a, b))
            a = b = c
    out.append((a, b))
    return ",".join(f"U+{x:X}" if x == y else f"U+{x:X}-{y:X}" for x, y in out)


UNICODE_RANGE = _unicode_range()


def subset_path(font_id: int, file_version) -> Path:
    """파일 판과 글자 집합 판을 이름에 넣는다. 둘 중 뭐가 바뀌든 새 파일이 된다."""
    return SUBSETS_DIR / f"s{font_id:03d}-{file_version}-{CHARSET_VERSION}.woff2"


def has_subset(font_id: int, file_version) -> bool:
    try:
        p = subset_path(font_id, file_version)
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


def build_subset(src: Path, dst: Path) -> bool:
    """원본 하나를 서브셋으로 굽는다. 폰트당 3~5초 걸린다(woff2 압축이 대부분).

    다 만든 뒤 원자적으로 옮긴다 — 반쯤 쓰인 파일을 브라우저가 받아 가면
    그 폰트가 깨진 채로 캐시된다.
    """
    from fontTools.ttLib import TTFont
    from fontTools.subset import Subsetter, Options

    tmp = dst.with_suffix(".tmp%d" % os.getpid())
    try:
        o = Options()
        o.legacy_cmap = False        # 옛 맥 cmap은 브라우저가 거부하는 경우가 있다
        o.symbol_cmap = False
        o.name_IDs = ["*"]           # 패밀리명이 바뀌면 안 된다
        o.name_legacy = True
        o.name_languages = ["*"]
        o.layout_features = ["*"]    # 커닝·합자 유지
        o.glyph_names = False
        o.notdef_outline = True
        o.recalc_bounds = True
        o.recalc_timestamp = False
        o.drop_tables = []
        o.hinting = True
        o.desubroutinize = False

        f = TTFont(str(src))
        s = Subsetter(options=o)
        s.populate(unicodes={ord(c) for c in SUBSET_CHARS})
        s.subset(f)
        f.flavor = "woff2"
        f.save(str(tmp))
        tmp.replace(dst)
        return True
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


def ensure_subset(font_id: int) -> bool:
    """이 폰트의 서브셋을 (없으면) 만든다. 만들어져 있으면 바로 True."""
    from .routers.files import _pick_font_file, file_version_of

    ver = file_version_of(font_id)
    if not ver:
        return False
    dst = subset_path(font_id, ver)
    if dst.exists() and dst.stat().st_size > 0:
        return True
    src, _ = _pick_font_file(font_id, 0)
    if src is None:
        return False
    ok = build_subset(Path(src), dst)
    if ok:
        _prune_old(font_id, dst)
    return ok


def _prune_old(font_id: int, keep: Path) -> None:
    """같은 폰트의 옛 판을 지운다. 안 지우면 어드민이 파일을 바꿀 때마다 쌓인다."""
    try:
        for p in SUBSETS_DIR.glob(f"s{font_id:03d}-*.woff2"):
            if p != keep:
                p.unlink()
    except OSError:
        pass


# ── 배경에서 채우기 ──────────────────────────────────────────────
#
# 209종 × 3~5초 = 15분. 요청 처리를 굶기지 않도록 한 종마다 쉬어 간다.
# 다 만들기 전까지는 프론트가 서브셋 face를 안 걸고 원본을 쓴다 — 느릴 뿐
# 깨지지 않는다. user_data에 쌓이므로 재배포해도 다시 만들지 않는다.
_warm_lock = threading.Lock()
_warming = False
WARM_GAP = float(os.getenv("SUBSET_WARM_GAP", "2.5"))   # 한 종 만들고 쉬는 시간(초)


def warm_up_async(font_ids: list) -> None:
    global _warming
    with _warm_lock:
        if _warming:
            return
        _warming = True

    def run():
        global _warming
        made = failed = 0
        try:
            for fid in font_ids:
                try:
                    if ensure_subset(fid):
                        made += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                time.sleep(WARM_GAP)
        finally:
            _warming = False
            print(f"[subset] 채우기 끝: 준비 {made} · 실패 {failed} "
                  f"· 글자 {len(SUBSET_CHARS)}자 · 집합판 {CHARSET_VERSION}",
                  flush=True)

    threading.Thread(target=run, name="subset-warmup", daemon=True).start()
