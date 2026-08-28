"""라이선스 전문(全文) — 상세페이지에서 '펼쳐 보기'로 따로 받는 자리.

왜 페이지 HTML 에 미리 넣지 않나
------------------------------
전문은 4,000자가 넘고, OFL 은 60종 넘는 폰트가 글자 하나까지 같다. 그걸 상세
페이지마다 실으면 폰트가 달라도 페이지의 대부분이 같아진다 — 그동안 줄여 온
중복 콘텐츠를 스스로 만드는 셈이다. 그래서 화면에는 요약만 두고, 전문은
사용자가 펼칠 때 API 로 따로 받는다. 크롤러가 읽는 SSR 에도 넣지 않는다.

전문은 어디서 오나
-----------------
1. meta.license.full — 어드민에서 직접 넣은 것. 있으면 무조건 이것을 쓴다.
2. 없고 라이선스 이름이 OFL 계열이면 OFL 1.1 정본.
   OFL 은 폰트마다 맨 위 저작권 한 줄만 다르고 본문은 같은 문서다. 실제로
   우리가 가진 배포본 네 개(BonaNova·Cinzel·DancingScript·Petrona)의 OFL.txt
   를 맞춰 보니 SIL 주소의 http/https 한 글자 말고는 같았다. 그래서 본문을
   한 벌만 두고 공유한다 — 폰트마다 복사해 두면 고칠 일이 생겼을 때 어긋난다.
3. 둘 다 아니면 없음. 지어내지 않는다 — 화면은 저작권자 원문 링크만 보여준다.
"""
import re
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "licenses"

# 라이선스 이름이 이 꼴이면 OFL 로 본다. note 까지 뒤지지는 않는다 —
# "OFL 을 따릅니다" 같은 설명문에 걸려 엉뚱한 폰트에 전문을 붙일 수 있다.
_OFL_NAME = re.compile(r"(?i)\bOFL\b|open\s+font\s+license")

_cache: dict[str, str] = {}


def _read(name: str) -> str:
    if name not in _cache:
        try:
            _cache[name] = (_DIR / name).read_text(encoding="utf-8").strip()
        except OSError:
            _cache[name] = ""
    return _cache[name]


def full_text(lic) -> tuple[str, str]:
    """(전문, 출처 한 줄). 없으면 ("", "").

    출처를 함께 돌려주는 이유: OFL 정본은 '이 폰트 파일에서 꺼낸 것'이 아니라
    '표준 문서를 우리가 붙인 것'이다. 화면에 그 사실을 밝히지 않으면 배포처가
    준 문서를 그대로 보여주는 것처럼 읽힌다.
    """
    if not isinstance(lic, dict):
        return "", ""

    own = str(lic.get("full") or "").strip()
    if own:
        return own, ""

    if _OFL_NAME.search(str(lic.get("name") or "")):
        t = _read("OFL-1.1.txt")
        if t:
            return t, ("SIL Open Font License 1.1 표준 전문입니다. "
                       "폰트마다 다른 저작권 표기는 저작권자 원문에서 확인하세요.")
    return "", ""
