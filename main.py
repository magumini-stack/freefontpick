# 카페24 ASGI 진입점
# 카페24가 루트의 main.py에서 'app' 변수를 ASGI 앱으로 인식한다.
from app.main import app  # noqa: F401

# 직접 실행 가능하도록 (개발/디버그용)
if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
