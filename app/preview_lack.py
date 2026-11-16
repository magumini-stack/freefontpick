"""미리보기 문구에 쓰는 한글 가운데 그 폰트에 없는 글자 (2026-11-13).

사용자님 11/13 "리아체.. 미리보기에서 '떤'이 제대로 안나와" → 2번(사이트 전체 규칙).
리아체(#147)는 한글을 1,339자만 담은 브랜드 서체라 '떤'·'떠'가 없다. 견본 문구에 그 글자가 있으면 그 자리만
다른 글꼴로 떨어져 깨져 보였다. 그래서 폰트마다 '견본 문구 글자 중 없는 것'(lack)을 알아 두고, 문구를 고르는 곳
(갤러리 /fonts·상세페이지·메인 카드)이 그 글자가 든 문구를 건너뛴다.

무엇을 보나
  견본 문구 뱅크(static/ffp-phrases.js·app/home_phrases.py·design._PREVIEW_PHRASES)의 한글 음절만.
  폰트 대표 파일의 cmap 에 그 글자가 있는지만 본다 — 글자 수를 세지 않는다(사용자님 "글자수는 중요한 변수가 아니야").
  영문 전용 폰트는 영문 문구를 쓰므로 보지 않는다.

요청을 기다리게 하지 않는다
  모르는 폰트는 '없는 글자 없음'으로 보고(예전과 같은 화면), 뒤에서 따로 띄운 파이썬 프로세스(nice 10)가 한 번에
  여러 폰트를 읽어 user_data/preview_lack.json 에 적는다(같은 프로세스 스레드로 fontTools 를 돌리면 요청이 느려진다 —
  font_subset.py 의 2026-10-01 장애). 폰트 파일이 바뀌면(이름·mtime·크기) 다시 읽는다. 다음 목록 굽기(5분)부터 반영된다.

    python -m app.preview_lack <id> <id> …   (일꾼이 부르는 자리 — 결과를 JSON 한 줄로 찍는다)
"""
import json
import os
import re
import sys
import threading
from pathlib import Path

_HANGUL = re.compile(r"[가-힣]")
_STORE = Path(os.getenv("PREVIEW_LACK_PATH", "/app/user_data/preview_lack.json"))
_lock = threading.Lock()
_data = None          # {"<id>": {"k": 파일 표시, "s": 문구 지문, "lack": "떠떤"}}
_queued = set()
_worker = None
_chars_cache = None


def phrase_chars() -> str:
    """견본 문구 뱅크의 한글 음절 모음."""
    global _chars_cache
    if _chars_cache is not None:
        return _chars_cache
    s = set()
    try:
        js = Path(__file__).resolve().parent.parent / "static" / "ffp-phrases.js"
        s.update(_HANGUL.findall(js.read_text(encoding="utf-8")))
    except OSError:
        pass
    try:
        from . import home_phrases as hp
        for v in hp.HOME_PHRASES.values():
            s.update(_HANGUL.findall("".join(v)))
        s.update(_HANGUL.findall("".join(hp.POPULAR_SAMPLE)))
    except Exception:
        pass
    try:
        from .routers.design import _PREVIEW_PHRASES
        s.update(_HANGUL.findall("".join(ko for ko, _ in _PREVIEW_PHRASES)))
    except Exception:
        pass
    _chars_cache = "".join(sorted(s))
    return _chars_cache


def _sig() -> str:
    import hashlib
    return hashlib.sha1(phrase_chars().encode("utf-8")).hexdigest()[:8]


def _file_of(font_id: int):
    try:
        from .routers.files import _pick_font_file
        p, _ = _pick_font_file(font_id, 0)
        return p
    except Exception:
        return None


def _key(p: Path) -> str:
    try:
        st = p.stat()
        return "%s-%d-%d" % (p.name, int(st.st_mtime), st.st_size)
    except OSError:
        return ""


def _load():
    global _data
    if _data is None:
        try:
            _data = json.loads(_STORE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _data = {}
    return _data


def lack_of(font) -> str:
    """그 폰트에 없는 견본 문구 글자. 모르면 "" (그리고 뒤에서 알아 둔다). 절대 오래 걸리지 않는다."""
    try:
        if font is None or font.is_english or not font.has_file:
            return ""
        p = _file_of(font.id)
        if p is None:
            return ""
        k, s = _key(p), _sig()
        with _lock:
            row = _load().get(str(font.id))
            if row and row.get("k") == k and row.get("s") == s:
                return row.get("lack") or ""
            if font.id not in _queued:
                _queued.add(font.id)
                _ensure_worker()
        return ""
    except Exception:  # noqa: BLE001 — 덤으로 고르는 장치라 실패하면 예전 화면
        return ""


def _ensure_worker():
    """_lock 을 쥔 채로 부른다."""
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    _worker = threading.Thread(target=_run, name="preview-lack", daemon=True)
    _worker.start()


def _run():
    import subprocess
    import time
    root = Path(__file__).resolve().parent.parent
    pre = (lambda: os.nice(10)) if os.name == "posix" else None
    while True:
        time.sleep(2)                      # 목록 굽기 한 번이 건 일감을 모아서 한꺼번에
        with _lock:
            ids = sorted(_queued)[:80]
        if not ids:
            return
        try:
            r = subprocess.run([sys.executable, "-m", "app.preview_lack"] + [str(i) for i in ids],
                               cwd=str(root), preexec_fn=pre, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=900)
            got = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {}
        except Exception as e:  # noqa: BLE001
            print("[preview-lack] 실패:", type(e).__name__, e, flush=True)
            got = {}
        with _lock:
            d = _load()
            d.update(got)
            _queued.difference_update(ids)
            try:
                _STORE.parent.mkdir(parents=True, exist_ok=True)
                tmp = _STORE.with_suffix(".tmp")
                tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                tmp.replace(_STORE)
            except OSError:
                pass
        if got:
            print("[preview-lack] %d종 확인" % len(got), flush=True)


def _measure(ids):
    """자식 프로세스: 폰트마다 대표 파일 cmap 에 견본 글자가 있는지 본다."""
    from fontTools.ttLib import TTFont
    from .routers.files import fill_font_resolution
    from .database import SessionLocal
    db = SessionLocal()
    try:
        fill_font_resolution(db)
    except Exception:
        pass
    finally:
        db.close()
    chars, s, out = phrase_chars(), _sig(), {}
    for fid in ids:
        p = _file_of(fid)
        if p is None:
            continue
        try:
            cmap = TTFont(str(p), lazy=True).getBestCmap() or {}
        except Exception:
            continue
        out[str(fid)] = {"k": _key(p), "s": s, "lack": "".join(c for c in chars if ord(c) not in cmap)}
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(_measure([int(a) for a in sys.argv[1:] if a.isdigit()]), ensure_ascii=False))
