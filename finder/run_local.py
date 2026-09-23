"""로컬 시험용 — 실험실(Desktop\\projects\\fontfinder-lab)의 폰트 목록·캐시로 finder 서비스를 띄운다.

    fontfinder-lab\\.venv\\Scripts\\python.exe finder\\run_local.py      (→ http://127.0.0.1:8010)

서버에서는 이 파일을 쓰지 않는다(docker compose 가 service:app 을 바로 띄운다).
"""
import os
import sys

for stream in (sys.stdout, sys.stderr):        # 윈도 콘솔(cp949)에서 한글 로그로 죽지 않게
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.environ.get("FINDER_LAB", r"C:\Users\jypark\Desktop\projects\fontfinder-lab")
os.environ.setdefault("FINDER_DATA", LAB)
os.environ.setdefault("FINDER_CATALOG", os.path.join(LAB, "catalog_all.json"))
os.environ.setdefault("FINDER_MAX_FONTS", "2000")      # 실험실 목록은 woff2 라 여는 데 오래 걸린다 — 다 열어 둔다
os.environ.setdefault("FINDER_MAX_STACKS", "60")
os.chdir(HERE)
sys.path.insert(0, HERE)

import uvicorn  # noqa: E402

uvicorn.run("service:app", host="127.0.0.1", port=int(os.environ.get("FINDER_PORT", "8010")), workers=1)
