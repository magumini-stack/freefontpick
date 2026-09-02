"""공개 페이지가 쓰는 tabler 아이콘만 골라 CSS 한 장으로 굽는다.

왜
--
아이콘 몇 개 쓰자고 아이콘 폰트 전체(tabler-icons.woff2, 475KB)를 외부
CDN 에서 받고 있었다. 공개 페이지가 실제로 쓰는 건 43종뿐이다.

무엇을 만드나
------------
static/ti-icons.css — 클래스 이름은 그대로 두고(.ti .ti-search) 구현만
아이콘 폰트에서 **CSS 마스크**로 바꾼다. 마크업은 한 글자도 안 고친다.

    .ti          { mask: var(--ti); background: currentColor; ... }
    .ti-search   { --ti: url("data:image/svg+xml,...") }

배경색을 currentColor 로 두는 게 핵심이다. 아이콘 폰트가 글자색을 따라가던
동작이 그대로 유지된다. 크기도 1em 이라 font-size 를 따라간다.

어드민은?
--------
static/admin.html 은 34종을 쓰고 로그인 뒤에 있어서 그대로 둔다. 거기서는
계속 아이콘 폰트를 쓴다. 두 방식이 한 페이지에서 겹치면 아이콘이 두 번
그려지므로, admin.html 에는 이 CSS 를 넣지 않는다.

다시 돌리기
----------
아이콘을 새로 쓰기 시작했으면 이 스크립트를 다시 돌린다. 쓰는 아이콘은
소스에서 직접 훑으므로 목록을 따로 관리하지 않는다.

    python tools/make_ti_icons.py

Tabler Icons 는 MIT 라이선스다 (https://github.com/tabler/tabler-icons).
"""
import io
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "ti-icons.css"
VER = "3.44.0"
CDN = "https://cdn.jsdelivr.net/npm/@tabler/icons@%s/icons/%s/%s.svg"

# 아이콘을 훑을 파일 — 공개 페이지만. admin* 은 뺀다.
SOURCES = [
    "static/index.html", "static/font.html", "static/about.html",
    "static/faq.html", "static/magazine.html", "static/policy.html",
    "static/privacy.html", "static/use.html", "static/wisefont.html",
    "static/gif.html", "static/gif-templates.html", "static/font-pair.html",
    "static/404.html", "app/header.py",
    # 아이콘 이름이 데이터로 들어 있는 곳. 매거진은 글마다
    # "icon": "ti-photo" 처럼 적어 두고 목록 카드에서 쓴다.
    "app/magazine.py", "app/use_case_data.py", "app/gif_template_data.py",
    # 라우터가 들고 있는 대비값도 넣는다 (아이콘을 안 적은 글에 쓰인다).
    "app/routers/magazine.py", "app/routers/use_case_route.py",
]


def used_icons():
    """소스에서 실제로 쓰는 아이콘 이름을 긁어 온다.

    두 가지 형태를 모두 잡아야 한다. 처음에는 앞의 것만 봤다가 다크모드
    토글(ti-sun · ti-moon)과 닫기 버튼(ti-x), 매거진 카드 아이콘이 통째로
    빠졌다 — 그림이 조용히 사라지는 종류의 사고라 눈에 잘 안 띈다.

        class="ti ti-search"    마크업에 직접 쓴 것
        "icon": "ti-photo"      데이터로 적어 둔 것
    """
    names = set()
    for rel in SOURCES:
        p = ROOT / rel
        if not p.exists():
            continue
        s = io.open(p, encoding="utf-8", errors="replace").read()
        names.update(re.findall(r"\bti ti-([a-z0-9-]+)", s))
        names.update(re.findall(r"""['"]ti-([a-z0-9-]+)['"]""", s))
    return sorted(names)


def fetch(name):
    """outline 을 먼저 보고, -filled 로 끝나면 filled 쪽을 본다."""
    tries = []
    if name.endswith("-filled"):
        tries.append(("filled", name[: -len("-filled")]))
    tries.append(("outline", name))
    tries.append(("filled", name))
    for kind, base in tries:
        try:
            with urllib.request.urlopen(CDN % (VER, kind, base), timeout=30) as r:
                if r.status == 200:
                    return r.read().decode("utf-8")
        except Exception:
            continue
    return None


def to_data_uri(svg):
    """마스크로 쓸 수 있게 다듬고 data: URI 로 만든다.

    마스크 안에서는 currentColor 가 상속되지 않는다. 알파만 쓰이므로
    불투명한 색으로 못 박아 둔다.
    """
    svg = re.sub(r'\sclass="[^"]*"', "", svg)          # 안 쓰는 class 제거
    svg = svg.replace('stroke="currentColor"', 'stroke="#000"')
    svg = svg.replace('fill="currentColor"', 'fill="#000"')
    svg = re.sub(r"\s*\n\s*", " ", svg).strip()         # 한 줄로
    svg = re.sub(r"\s{2,}", " ", svg)
    svg = svg.replace('"', "'")                         # CSS url("...") 안에서 쓰려고
    for a, b in (("%", "%25"), ("#", "%23"), ("<", "%3C"), (">", "%3E")):
        svg = svg.replace(a, b)
    return svg


HEAD = """/* 아이콘 — tabler icons %s 중 공개 페이지가 쓰는 것만 (MIT)
   https://github.com/tabler/tabler-icons

   tools/make_ti_icons.py 가 만든다. 직접 고치지 말고 스크립트를 다시 돌릴 것.
   아이콘 폰트(475KB)를 외부에서 받던 것을 대신한다. 클래스 이름은 그대로라
   마크업은 손대지 않았다.

   admin.html 은 여기 없는 아이콘을 쓰므로 계속 아이콘 폰트를 쓴다.
   두 방식이 한 페이지에서 겹치면 아이콘이 두 번 그려진다 — 같이 넣지 말 것. */
.ti {
  display: inline-block;
  width: 1em;
  height: 1em;
  vertical-align: -0.125em;
  /* 글자색을 따라간다 — 아이콘 폰트와 같은 동작 */
  background-color: currentColor;
  -webkit-mask: var(--ti) no-repeat center;
  mask: var(--ti) no-repeat center;
  -webkit-mask-size: contain;
  mask-size: contain;
  flex: none;
}
"""


def main():
    names = used_icons()
    print("공개 페이지가 쓰는 아이콘 %d종" % len(names))
    rules, missing = [], []
    for n in names:
        svg = fetch(n)
        if not svg:
            missing.append(n)
            continue
        rules.append(".ti-%s{--ti:url(\"data:image/svg+xml,%s\")}" % (n, to_data_uri(svg)))
    css = (HEAD % VER) + "\n".join(rules) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(css)
    print("%s — %d종 · %.1f KB" % (OUT.name, len(rules), len(css.encode()) / 1024))
    if missing:
        print("!! 못 받은 아이콘: %s" % ", ".join(missing))
        print("   이 아이콘들은 화면에서 사라진다. 이름을 확인할 것.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
