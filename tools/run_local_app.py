"""로컬 시험용 — 앱을 SQLite(local.db)로 띄우고 /api/find/* 는 로컬 finder(:8010)로 넘긴다.

    .venv\\Scripts\\python.exe tools\\run_local_app.py      (→ http://localhost:8000)

finder 는 따로 띄운다: fontfinder-lab\\.venv\\Scripts\\python.exe finder\\run_local.py
"""
import os
import sys

# 앱이 시작하며 찍는 로그에 한글·긴 줄표가 있다 — 윈도 콘솔(cp949)에서 UnicodeEncodeError 로 죽지 않게 UTF-8 로
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("LOCAL_DB_PATH", os.path.join(ROOT, "local.db"))
os.environ.setdefault("FORCE_SQLITE", "1")
os.environ.setdefault("FINDER_URL", "http://127.0.0.1:8010")

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), reload=False)
