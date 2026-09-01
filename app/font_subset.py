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
        for mod in ("pair_specimens", "pairing_phrases", "pairing_data"):
            try:
                import importlib
                m = importlib.import_module("." + mod, __package__)
                for v in vars(m).values():
                    _collect(v, chars)
            except Exception:
                pass

        # 폰트 이름과 제작사 — 미리보기 카드에 그대로 찍힌다.
        try:
            from .database import SessionLocal
            from .models import Font
            db = SessionLocal()
            try:
                for name, maker in db.query(Font.name, Font.maker).all():
                    chars.update(name or "")
                    chars.update(maker or "")
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


def cache_path(src: Path) -> Path:
    """원본 파일에 대응하는 서브셋 캐시 경로.

    mtime·크기를 이름에 넣어, 어드민이 파일을 바꾸면 저절로 새 이름이 된다.
    글자 목록의 지문도 함께 넣는다 — _text_sig 주석 참고.
    """
    try:
        st = src.stat()
        sig = "%d-%d" % (int(st.st_mtime), st.st_size)
    except OSError:
        sig = "0-0"
    return CACHE_DIR / ("%s.v%d.%s.%s.woff2"
                        % (src.stem, VERSION, _text_sig(), sig))


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


# 마지막 오류를 남겨 둔다. 운영 로그를 볼 수 없는 환경이라, 이게 없으면
# 서브셋이 왜 안 생기는지 알 방법이 없다 (/api/debug/subset 이 읽어 간다).
_last_error = None
_made = 0


def _run():
    global _last_error, _made
    while True:
        src = _jobs.get()
        dst = cache_path(src)
        try:
            _make(src, dst)
            _made += 1
        except Exception as e:
            import traceback
            with _state_lock:
                _failed.add(str(dst))
                _last_error = "%s: %s: %s" % (
                    src.name, type(e).__name__, traceback.format_exc()[-600:])
            print("[subset] 실패 %s: %s: %s" % (src.name, type(e).__name__, e),
                  flush=True)
        finally:
            with _state_lock:
                _queued.discard(str(dst))
            _jobs.task_done()


def status() -> dict:
    """서브셋이 왜 안 생기는지 밖에서 들여다보기 위한 창."""
    info = {
        "cache_dir": str(CACHE_DIR),
        "cache_dir_exists": CACHE_DIR.exists(),
        "version": VERSION,
        "made": _made,
        "queued": len(_queued),
        "failed": len(_failed),
        "worker_alive": bool(_worker and _worker.is_alive()),
        "last_error": _last_error,
    }
    try:
        t = preview_text()
        info["preview_chars"] = len(t)
        info["text_sig"] = _text_sig()
    except Exception as e:
        info["preview_text_error"] = "%s: %s" % (type(e).__name__, e)
    try:
        files = sorted(CACHE_DIR.glob("*.woff2"))
        info["cached_files"] = len(files)
        info["sample"] = [f.name for f in files[:5]]
    except Exception as e:
        info["cache_list_error"] = "%s: %s" % (type(e).__name__, e)
    return info


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
        return

    # 같은 이름으로 곧장 쓰면 다 못 쓴 파일을 남이 읽어 갈 수 있다.
    tmp = dst.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(str(tmp), str(dst))
    print("[subset] %s  %d -> %d (%.0f%%)"
          % (src.name, src_size, len(data), 100.0 * len(data) / src_size),
          flush=True)
