"""공유 이미지(og:image) 한 장을 별도 프로세스에서 만든다.

    python -m app.og_build font 123
    python -m app.og_build hub card

왜 프로세스를 따로 띄우나
------------------------
2026-09-27 생성을 일꾼 스레드로 뒤로 돌렸는데도, 만드는 동안 /api/fonts 가 60초
시간초과를 냈다. 생성은 Pillow·fontTools 가 CPU 를 오래 붙잡는 일이라, 같은
프로세스 안에서는 스레드를 나눠도 파이썬 GIL 을 두고 다투어 다른 요청이 거의
돌지 못한다. 프로세스를 나누면 GIL 이 따로라 앱은 제 속도로 응답한다.

nice 를 올려 CPU 도 앱에 먼저 양보한다. 한 번에 하나만 돈다(app/routers/og_image.py
의 일꾼이 끝나기를 기다렸다가 다음 것을 띄운다).
"""
import os
import sys


def main(argv) -> int:
    if len(argv) != 2 or argv[0] not in ("font", "hub"):
        print("usage: python -m app.og_build font <id> | hub <slug>", file=sys.stderr)
        return 2
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass

    from .database import SessionLocal
    from .models import Font
    from .routers import og_image as og

    kind, arg = argv
    db = SessionLocal()
    try:
        if kind == "font":
            font = db.query(Font).filter(Font.id == int(arg)).first()
            if font is None:
                return 0
            og._ensure_cached(font)
        else:
            og._build_hub(db, arg)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
