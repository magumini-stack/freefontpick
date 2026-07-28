"""웹폰트 등록값 검증.

어드민이 폰트를 등록할 때 `webfont_css_url` / `webfont_family` / `webfont_weights`를
직접 입력하는데, 지금까지는 아무 검증이 없었다. 그래서 다음 같은 실수가 조용히
통과하고, 화면에는 굵기 줄이 멀쩡히 그려져서 알아채기 어려웠다.

  - 구름산스: 구글폰트에 없는 폰트인데 `fonts.googleapis.com/css2?family=구름산스...`로
    등록 → 구글이 400을 반환해 @font-face가 하나도 오지 않음 → 폴백 서체로 렌더되어
    400과 500이 똑같이 보임
  - IBM Plex Sans KR: 100~900으로 등록했지만 실제 CSS는 100~700만 제공 → 800/900 줄이
    700과 구분되지 않음

이 모듈은 CSS를 실제로 받아와서 세 가지를 확인한다.
  1) @font-face가 실제로 오는가
  2) CSS가 선언한 font-family가 등록한 webfont_family와 일치하는가
  3) CSS가 제공하는 굵기가 등록한 webfont_weights를 포함하는가
"""
import re
import urllib.error
import urllib.parse
import urllib.request

# 구글폰트는 User-Agent에 따라 다른 CSS를 준다(구형 UA면 woff2 대신 ttf).
# 최신 브라우저인 척해야 실제 방문자가 받는 것과 같은 CSS를 검증할 수 있다.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_TIMEOUT = 8.0
_MAX_BYTES = 2_000_000

_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}]+)", re.I)
_WEIGHT_RE = re.compile(r"font-weight\s*:\s*([^;}]+)", re.I)


def _norm_family(raw: str) -> str:
    """'Goorm Sans' / \"Goorm Sans\" / Goorm Sans → goorm sans"""
    s = raw.strip().strip("'\"").strip()
    return re.sub(r"\s+", " ", s).lower()


def _iter_font_face_blocks(css: str):
    """@font-face { ... } 블록 본문을 하나씩 내어준다 (중괄호 깊이로 끝을 찾음)."""
    for m in re.finditer(r"@font-face\s*\{", css, re.I):
        depth, i = 1, m.end()
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        yield css[m.end():i - 1]


def parse_css(css: str) -> dict:
    """CSS에서 (선언된 font-family 집합, 지원 굵기)를 뽑는다.

    굵기는 `font-weight: 700` 같은 단일값과 가변폰트의 `font-weight: 100 900`
    범위 표기를 모두 처리한다.
    """
    # families는 비교용(소문자 정규화), display는 화면에 그대로 보여줄 원본 표기.
    # 어드민이 "CSS에 적힌 이름 그대로" 채워 넣을 수 있어야 하므로 원본을 살려둔다.
    families, display, exact, ranges = set(), [], set(), set()
    faces = 0
    for block in _iter_font_face_blocks(css):
        faces += 1
        fm = _FAMILY_RE.search(block)
        if fm:
            # src의 url(...) 안에 font-family가 들어갈 일은 없으므로 첫 매칭이면 충분
            key = _norm_family(fm.group(1))
            if key not in families:
                display.append(fm.group(1).strip().strip("'\"").strip())
            families.add(key)
        wm = _WEIGHT_RE.search(block)
        if wm:
            nums = re.findall(r"\d+", wm.group(1))
            if len(nums) >= 2:
                # 가변폰트는 서브셋마다 같은 범위를 반복 선언하므로 set으로 중복 제거
                ranges.add((int(nums[0]), int(nums[1])))
            elif len(nums) == 1:
                exact.add(int(nums[0]))
    return {"faces": faces, "families": families, "display": display,
            "exact": exact, "ranges": sorted(ranges)}


def _supports(parsed: dict, w: int) -> bool:
    if w in parsed["exact"]:
        return True
    return any(lo <= w <= hi for lo, hi in parsed["ranges"])


def _encode_url(url: str) -> str:
    """URL에 든 한글 등 비ASCII 문자를 퍼센트 인코딩한다.

    브라우저는 알아서 인코딩해 보내지만 urllib은 비ASCII가 있으면 그대로 예외를 낸다.
    (구름산스처럼 `family=구름산스`가 든 주소가 실제로 등록돼 있어서, 인코딩하지 않으면
    서버가 준 HTTP 400 대신 UnicodeEncodeError가 잡혀 원인을 오해하게 된다.)
    """
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def fetch_css(url: str) -> tuple:
    """(css_text, error_message). 실패하면 css_text는 ''."""
    try:
        req = urllib.request.Request(_encode_url(url), headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return r.read(_MAX_BYTES).decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as e:
        return "", f"CSS 주소가 HTTP {e.code}를 반환했습니다"
    except urllib.error.URLError as e:
        return "", f"CSS 주소에 연결하지 못했습니다 ({e.reason})"
    except Exception as e:  # noqa: BLE001 - 검증 실패가 등록을 막아선 안 된다
        return "", f"CSS 주소를 확인하지 못했습니다 ({e.__class__.__name__})"


def check_webfont(family: str, css_url: str, weights) -> dict:
    """웹폰트 등록값 검증 결과.

    반환: {ok, errors[], warnings[], info{}}
    - errors  : 이 상태로 두면 폰트가 아예 안 보이거나 굵기가 틀리게 나오는 문제
    - warnings: 동작은 하지만 확인이 필요한 것
    """
    family = (family or "").strip()
    css_url = (css_url or "").strip()
    weights = [int(w) for w in (weights or [])]
    errors, warnings = [], []
    # suggested_* 는 어드민 화면이 "이 값으로 고치기" 버튼에 쓰는 자동 채움 값이다.
    info = {"css_families": [], "css_weights": [], "face_count": 0,
            "suggested_family": None, "suggested_weights": []}

    if not css_url:
        if family:
            errors.append("webfont_family만 있고 webfont_css_url이 비어 있습니다")
        return {"ok": not errors, "errors": errors, "warnings": warnings, "info": info}

    if not family:
        errors.append("webfont_css_url만 있고 webfont_family가 비어 있습니다")

    css, err = fetch_css(css_url)
    if err:
        errors.append(err)
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    parsed = parse_css(css)
    info["face_count"] = parsed["faces"]
    info["css_families"] = parsed["display"]
    info["css_weights"] = sorted(parsed["exact"]) + [f"{lo}-{hi}" for lo, hi in parsed["ranges"]]
    if parsed["display"]:
        info["suggested_family"] = parsed["display"][0]
    if parsed["exact"]:
        info["suggested_weights"] = sorted(parsed["exact"])
    elif parsed["ranges"]:
        # 가변폰트는 범위 안의 표준 굵기를 모두 쓸 수 있다
        lo, hi = parsed["ranges"][0]
        info["suggested_weights"] = [w for w in range(100, 1000, 100) if lo <= w <= hi]

    if parsed["faces"] == 0:
        errors.append(
            "CSS에 @font-face가 하나도 없습니다. 이 주소로는 폰트가 로드되지 않아 "
            "폴백 서체로 표시됩니다 (구글폰트에 없는 폰트를 구글폰트 주소로 등록한 경우가 흔합니다)"
        )
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    if family and _norm_family(family) not in parsed["families"]:
        errors.append(
            f"CSS가 선언한 font-family와 다릅니다. 등록값 '{family}' → "
            f"CSS 선언 {info['css_families']}. 등록값을 CSS 선언과 똑같이 맞춰야 적용됩니다"
        )

    missing = [w for w in weights if not _supports(parsed, w)]
    if missing:
        warnings.append(
            f"CSS가 제공하지 않는 굵기입니다: {missing}. 해당 굵기는 가장 가까운 "
            f"굵기로 대체되어 다른 줄과 똑같이 보입니다 (CSS 제공: {info['css_weights']})"
        )

    if weights:
        extra = [w for w in sorted(parsed["exact"]) if w not in weights]
        if extra:
            warnings.append(f"CSS에는 있지만 등록되지 않은 굵기: {extra}")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "info": info}
