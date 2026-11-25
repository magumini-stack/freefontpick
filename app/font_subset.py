"""미리보기용 폰트 서브셋.

왜 필요한가
----------
상세페이지 한 장에서 폰트 파일만 1.8MB 가 나간다. 그런데 그중 본체
폰트를 뺀 나머지는 폰트 이름 몇 글자와 짧은 견본 문구를 그리는 데만
쓰인다. 글리프 1만 개짜리 한글 폰트를 통째로 내려주고 스무 글자를
그리는 셈이다.

실측한 값이다.

    569KB -> 57KB (10%)   449KB -> 97KB (22%)
    404KB -> 84KB (21%)   117KB -> 42KB (36%)

무엇을 남기나
------------
미리보기에 나올 수 있는 글자를 전부 모아 한 벌로 만든다.

    폰트 이름·제작사 (239종)  +  조합 샘플 문구  +  글자 견본
    +  영문 대소문자 · 숫자 · 자주 쓰는 기호

920자쯤 된다. 폰트마다 다른 글자로 만들지 않는 이유는, 어떤 폰트가
어떤 조합에 뽑힐지 미리 알 수 없기 때문이다. 한 벌로 통일해 두면
무엇에 뽑히든 글자가 빠지지 않는다.

왜 요청을 기다리게 하지 않나
--------------------------
app/routers/og_image.py 에 실측이 남아 있다. 서브셋 한 건이 순간
+58MB 를 잡아먹어서, 동시에 여러 건이 돌면 컨테이너가 죽었다(502).
상세페이지 한 장이 폰트 열 개를 부르는 우리 경우엔 더 위험하다.

그래서 **요청은 절대 기다리지 않는다.**

    캐시에 있으면  ->  서브셋을 준다
    캐시에 없으면  ->  원본을 그대로 주고, 뒤에서 하나씩 만든다

만드는 일은 일꾼 스레드 하나가 순서대로 한다. 동시에 여러 개를 만들지
않으므로 메모리가 배수로 튀지 않는다. 두 번째 방문부터 서브셋이 나간다.
서브셋이 아직 없다고 화면이 깨지는 일은 없다 — 원본이 나가니까.

캐시는 어디 두나
--------------
/app/user_data 아래에 둔다. 카페24가 배포 때 보존하는 자리라, 새로
배포해도 처음부터 다시 만들지 않는다.

원본 파일이 바뀌면(어드민이 새로 올리면) 캐시 이름에 든 mtime·크기가
달라져 자동으로 새로 만든다. 옛 파일은 남지만 이름이 달라 섞이지 않는다.
"""
import os
import queue
import threading
from pathlib import Path

# 판 번호. 아래 글자 목록이나 서브셋 옵션을 바꾸면 올린다 — 캐시 이름이
# 달라져서 전부 다시 만들어진다.
VERSION = 1

CACHE_DIR = Path(os.getenv("FONT_SUBSET_DIR", "/app/user_data/font_subsets"))

# 서브셋이 이보다 작아지지 않으면 원본을 그대로 쓴다. 영문 전용 폰트처럼
# 원래 가벼운 것은 굳이 파일을 하나 더 두고 관리할 이유가 없다.
MIN_GAIN = 0.85

# 화면에 늘 나오는 글자 — 상세페이지 '글자 견본' 세 줄과 같은 구성이다.
_FIXED = (
    "가나다라마바사아자차카타파하"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    " .,!?·…—-~/:;'\"()[]{}%&*+=<>@#₩$€£¥"
)

_text_cache = None
_text_lock = threading.Lock()


def preview_text() -> str:
    """서브셋에 남길 글자 모음. 한 번 만들면 프로세스가 살아 있는 동안 쓴다."""
    global _text_cache
    if _text_cache is not None:
        return _text_cache
    with _text_lock:
        if _text_cache is not None:
            return _text_cache
        chars = set(_FIXED)

        # 조합 샘플 문구 — 모듈 안의 문자열을 통째로 훑는다. 변수 이름까지
        # 섞여 들어오지만 영숫자라 서브셋이 커지지 않는다.
        # home_phrases 는 홈 카드가 그리는 문구다. 2026-09-23 이전에는 빠져 있어
        # '버텼어'의 텼, '눌러'의 눌 처럼 조합 문구에 없던 글자가 카드에서만
        # 두부로 나왔다(상세페이지는 원본을 쓰므로 멀쩡했다).
        for mod in ("pair_specimens", "pairing_phrases", "pairing_data", "home_phrases"):
            try:
                import importlib
                m = importlib.import_module("." + mod, __package__)
                for v in vars(m).values():
                    _collect(v, chars)
            except Exception:
                pass

        # 갤러리(/fonts) 카드 문구 — 파이썬이 아니라 static/ffp-phrases.js 에 산다.
        # 파일을 글자 단위로 훑는다(자바스크립트 문법은 영숫자라 서브셋이 안 커진다).
        try:
            js = Path(__file__).resolve().parent.parent / "static" / "ffp-phrases.js"
            chars.update(js.read_text(encoding="utf-8"))
        except OSError:
            pass

        # 폰트 이름·제작사와 어드민이 넣은 문구 — 미리보기 카드에 그대로 찍힌다.
        try:
            from .database import SessionLocal
            from .models import Font, FontPairing, PreviewPhrase, UseCase, UseCasePhrase
            db = SessionLocal()
            try:
                for name, maker in db.query(Font.name, Font.maker).all():
                    chars.update(name or "")
                    chars.update(maker or "")
                # 용도 이름 — /fonts 용도 칸이 "굿즈 · 스티커" 같은 이름을 그 용도의
                # 대표 폰트로 그린다. 빠져 있어 '굿'이 다른 글꼴로 떨어졌다(2026-09-26).
                for (title,) in db.query(UseCase.title).all():
                    chars.update(title or "")
                for (meta,) in db.query(Font.meta).all():
                    if isinstance(meta, dict):
                        chars.update(meta.get("preview_text") or "")
                for (text,) in db.query(PreviewPhrase.text).all():
                    chars.update(text or "")
                for (text,) in db.query(UseCasePhrase.text).all():
                    chars.update(text or "")
                # 조합 카드 견본 문구 — 11/18 부터 상세페이지 옆 조합 카드도 서브셋을 쓴다.
                # 시드(pairing_data)·문구 뱅크는 위에서 이미 모았고, 이것은 어드민이 직접 쓴 문구까지 챙긴다.
                for t, bd in db.query(FontPairing.sample_title, FontPairing.sample_body).all():
                    chars.update(t or "")
                    chars.update(bd or "")
            finally:
                db.close()
        except Exception:
            pass

        chars.discard("\n")
        chars.discard("\r")
        chars.discard("\t")
        _text_cache = "".join(sorted(chars))
        return _text_cache


def _collect(v, out, depth=0):
    """중첩된 자료구조 안의 문자열을 모은다."""
    if depth > 4:
        return
    if isinstance(v, str):
        out.update(v)
    elif isinstance(v, (list, tuple, set, frozenset)):
        for x in v:
            _collect(x, out, depth + 1)
    elif isinstance(v, dict):
        for k, x in v.items():
            _collect(k, out, depth + 1)
            _collect(x, out, depth + 1)


_text_sig_cache = None


def _text_sig() -> str:
    """글자 목록의 지문. 목록이 달라지면 캐시가 통째로 갈린다.

    폰트가 새로 등록되면 그 이름의 글자가 목록에 늘어난다. 지문을 이름에
    넣어 두지 않으면 옛 서브셋이 그대로 쓰여서, 어떤 글자가 조용히 빠진
    채로 보인다. 그런 종류의 버그는 눈에 잘 안 띈다.
    """
    global _text_sig_cache
    if _text_sig_cache is None:
        import hashlib
        _text_sig_cache = hashlib.sha1(
            preview_text().encode("utf-8")).hexdigest()[:8]
    return _text_sig_cache


# 조판 기능(GSUB·GPOS)을 남겨 둘 폰트 번호.
#
# 서브셋은 기본적으로 조판 기능을 전부 버린다(아래 _make). 그런데 글자 모양 자체가
# OpenType 기능으로 만들어지는 폰트는 그러면 카드에서 다른 폰트가 돼 버린다.
#
#   1015  노노아카이브 프렐류드 — 단어 끝 꼬리·첫 글자 말림(스와시)이 calt 로 저절로
#         붙는 폰트다. 서브셋에서 GSUB 를 버리니 카드에는 스와시 없는 기본 글자만
#         나왔다(2026-11-25 사용자님 지적). 상세페이지는 원본을 써서 멀쩡했다.
#
# 이런 폰트가 새로 들어오면 여기에 번호를 더한다. 글자 목록은 그대로 920자쯤이라
# 조판 기능을 남겨도 원본(698KB)보다 훨씬 작다.
KEEP_LAYOUT_IDS = {1015}

# 위 폰트들의 '판'을 이 시각 이후로 올린다(files.file_version_of 가 읽는다).
# 서브셋 주소는 판이 박힌 채 1년 immutable 로 나가서, 이미 받아 간 브라우저·CDN 에는
# 조판 기능 없는 옛 서브셋이 그대로 남는다. 판이 바뀌면 주소가 바뀌어 새로 받는다.
# 번호를 더할 때(새 calt 폰트)도, 이미 등록된 폰트라면 이 값을 올려 줘야 한다.
LAYOUT_EPOCH = 1795592000   # 2026-11-25


def keeps_layout(src: Path) -> bool:
    """이 파일의 서브셋에 조판 기능을 남기는가. 파일 이름(font-1015.woff2,
    font-1015-w400.woff2)에서 폰트 번호를 읽는다. 파일을 열지 않는다 — 요청마다 불린다."""
    import re
    m = re.match(r"font-(\d+)", src.stem)
    return bool(m) and int(m.group(1)) in KEEP_LAYOUT_IDS


def cache_path(src: Path) -> Path:
    """원본 파일에 대응하는 서브셋 캐시 경로.

    mtime·크기를 이름에 넣어, 어드민이 파일을 바꾸면 저절로 새 이름이 된다.
    글자 목록의 지문도 함께 넣는다 — _text_sig 주석 참고.
    조판 기능을 남기는 폰트는 이름에 '.L' 이 붙는다 — 옛 서브셋(기능 없음)과 겹치지 않고,
    다른 폰트의 캐시는 그대로 두므로 전체를 다시 만들 필요가 없다.
    """
    try:
        st = src.stat()
        sig = "%d-%d" % (int(st.st_mtime), st.st_size)
    except OSError:
        sig = "0-0"
    tag = ".L" if keeps_layout(src) else ""
    return CACHE_DIR / ("%s.v%d%s.%s.%s.woff2"
                        % (src.stem, VERSION, tag, _text_sig(), sig))


# 못 만드는 폰트를 매번 다시 시도하지 않도록 기억해 둔다.
_failed = set()
_queued = set()
_state_lock = threading.Lock()
_jobs: "queue.Queue[Path]" = queue.Queue()
_worker = None


def subset_or_none(src: Path):
    """서브셋이 준비돼 있으면 그 경로를, 아니면 None 을 돌려준다.

    None 이면 부르는 쪽이 원본을 내보내면 된다. 이 함수는 절대 오래
    걸리지 않는다 — 파일이 있는지 보고 없으면 일감만 걸어 둔다.
    """
    if not src:
        return None
    dst = cache_path(src)
    try:
        if dst.exists() and dst.stat().st_size > 0:
            return dst
    except OSError:
        return None

    key = str(dst)
    with _state_lock:
        if key in _failed or key in _queued:
            return None
        _queued.add(key)
        _ensure_worker()
    _jobs.put(src)
    return None


def _ensure_worker():
    """일꾼 스레드를 한 번만 띄운다. _state_lock 을 쥔 채로 부른다."""
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    _worker = threading.Thread(target=_run, name="font-subset", daemon=True)
    _worker.start()


# 서브셋은 따로 띄운 파이썬 프로세스(nice 10)에서 만든다 (2026-10-01 장애).
# fontTools 는 순수 파이썬이라 같은 프로세스 스레드에서 돌리면 GIL 을 놓고 요청들과
# CPU 한 개를 다툰다. 새 폰트가 들어와 글자 지문이 바뀌면 527종을 통째로 다시 만들어
# 몇 분씩 이어지고, 그동안 요청이 느려져 DB 연결이 바닥났다. 별도 프로세스면 서버의
# 남는 코어를 쓰고, nice 로 웹 요청보다 뒤에 선다.
_SKIP_RC = 3     # 줄어들지 않아 만들지 않음


def _make_in_child(src: Path, dst: Path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parent.parent
    pre = (lambda: os.nice(10)) if os.name == "posix" else None
    r = subprocess.run([sys.executable, "-m", "app.font_subset", str(src), str(dst)],
                       cwd=str(root), preexec_fn=pre, capture_output=True, text=True,
                       timeout=600)
    if r.stdout.strip():
        print(r.stdout.strip(), flush=True)
    if r.returncode == _SKIP_RC:
        with _state_lock:
            _failed.add(str(dst))
        return
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()
        raise RuntimeError(tail[-1] if tail else "exit %d" % r.returncode)


def _run():
    while True:
        src = _jobs.get()
        dst = cache_path(src)
        try:
            _make_in_child(src, dst)
        except Exception as e:
            # 실패는 표시해 두고 다시 시도하지 않는다. 원본이 그대로 나가므로
            # 화면은 멀쩡하다. 원인을 봐야 하면 이 줄이 컨테이너 로그에 남는다.
            with _state_lock:
                _failed.add(str(dst))
            print("[subset] 실패 %s: %s: %s" % (src.name, type(e).__name__, e),
                  flush=True)
        finally:
            with _state_lock:
                _queued.discard(str(dst))
            _jobs.task_done()


def _make(src: Path, dst: Path):
    """실제 서브셋 생성. 일꾼 스레드 하나만 이 안에 들어온다."""
    import gc
    import io as _io

    from fontTools import subset
    from fontTools.ttLib import TTFont

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    src_size = src.stat().st_size

    tt = TTFont(str(src), fontNumber=0, lazy=True)
    try:
        opt = subset.Options()
        opt.desubroutinize = False
        opt.hinting = False
        opt.notdef_glyph = True
        opt.notdef_outline = False
        opt.recalc_bounds = False
        opt.recalc_timestamp = False
        opt.legacy_kern = False
        opt.ignore_missing_glyphs = True
        opt.ignore_missing_unicodes = True
        # 이름 표(name)는 남긴다 — 라이선스·제작사 정보가 여기 들어 있다.
        opt.name_IDs = ["*"]
        # 조판 기능은 버린다. 미리보기는 짧은 글줄이라 합자·커닝이 없어도
        # 눈에 띄지 않는다. 이게 용량을 가장 많이 줄여 준다.
        # 다만 기능으로 글자 모양이 만들어지는 폰트(KEEP_LAYOUT_IDS)는 남긴다.
        # 기능을 켜 둔 채 글자 목록으로 줄이면 스와시 글리프도 목록 글자에 닿는 것만 남는다.
        if keeps_layout(src):
            opt.layout_features = ["*"]
            opt.drop_tables += ["kern", "DSIG"]
        else:
            opt.layout_features = []
            opt.drop_tables += ["GSUB", "GPOS", "GDEF", "kern", "DSIG"]

        ss = subset.Subsetter(options=opt)
        ss.populate(text=preview_text() + " ")
        ss.subset(tt)

        tt.flavor = "woff2"
        buf = _io.BytesIO()
        tt.save(buf)
        data = buf.getvalue()
    finally:
        try:
            tt.close()
        except Exception:
            pass
        del tt
        gc.collect()

    if not data or len(data) >= src_size * MIN_GAIN:
        # 줄어들지 않으면 만들지 않는다. 다음에 또 시도하지 않도록 기억해 둔다.
        with _state_lock:
            _failed.add(str(dst))
        print("[subset] 건너뜀 %s (%d -> %d, 이득 없음)"
              % (src.name, src_size, len(data)), flush=True)
        return False

    # 같은 이름으로 곧장 쓰면 다 못 쓴 파일을 남이 읽어 갈 수 있다.
    tmp = dst.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(str(tmp), str(dst))
    print("[subset] %s  %d -> %d (%.0f%%)"
          % (src.name, src_size, len(data), 100.0 * len(data) / src_size),
          flush=True)
    return True


if __name__ == "__main__":
    # _make_in_child 가 부른다: python -m app.font_subset <원본> <결과>
    import sys
    sys.exit(0 if _make(Path(sys.argv[1]), Path(sys.argv[2])) else _SKIP_RC)
