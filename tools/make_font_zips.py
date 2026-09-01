"""배포용 폰트 묶음(zip)을 만든다 — fontzips/font-NNN.zip

왜 필요한가
----------
몇몇 폰트는 상세페이지의 '무료 다운로드'가 구글 드라이브 링크로 나가고 있었다.
드라이브 파일 링크는 소유자가 지우거나 옮기면 그대로 끊기고, 받는 사람은
폰트픽을 떠나 낯선 화면에서 받게 된다. 관계사가 만들고 배포하는 폰트들이라
우리 서버에서 직접 내려주기로 했다.

무엇으로 만드나
-------------
운영이 실제로 내려주는 웹폰트 파일이다(/api/fonts/{id}/file). woff2 는 sfnt 를
압축한 그릇이라, flavor 만 벗기면 원래 ttf/otf 로 되돌아온다. 글리프가 깎이지
않는다 — 실제로 되돌린 파일의 한글 글자 수를 세어 확인한다(아래 --check).

⚠️ 제작사가 배포하는 원본 묶음과 **같지 않다.** 원본에는 굵기가 더 들어 있거나
ttf·otf 가 함께 있거나 라이선스 PDF 가 붙어 있을 수 있다. 여기 담기는 것은
'폰트픽이 화면에 쓰는 그 파일'이다. 굵기는 사이트가 가진 것을 모두 넣는다.

라이선스 안내는 지어내지 않는다
---------------------------
zip 안의 '라이선스 안내.txt' 는 사이트가 이미 공개하고 있는 값에서만 만든다 —
상세페이지의 허용 표와 /api/fonts/{id}/license 의 이름·원문 주소다. 손으로 적으면
사이트와 zip 이 갈라지고, 갈라진 쪽이 무엇인지 나중에 알 수 없다.

    python tools/make_font_zips.py 48 51 63 77 78 169
    python tools/make_font_zips.py --check 48        # 만들지 않고 확인만
"""
import argparse
import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
import os
from pathlib import Path

from fontTools.ttLib import TTFont

# 사이트 주소 — app/site.py 와 같은 환경변수를 본다.
# 도메인을 옮기면 SITE_URL 을 주고 돌린다.
BASE = os.getenv("SITE_URL", "https://freefontpick.co.kr").rstrip("/")
HOST = BASE.split("://", 1)[-1]   # 이미지에 글자로 찍을 때 쓴다
OUT = Path(__file__).resolve().parent.parent / "fontzips"
# 제작사 원본 문서(README·LICENSE 등)를 그대로 넣어야 하는 폰트가 있다.
# 여기 font-NNN/ 폴더를 만들어 두면 그 안의 파일이 **바이트 그대로** 묶인다.
# 다시 인코딩하지 않는 것이 중요하다 — 라이선스가 'verbatim copies' 를
# 요구하는 경우, 줄바꿈이나 문자표를 바꾸면 그 조건에서 벗어난다.
DOCS = OUT / "_docs"
UA = {"User-Agent": "Mozilla/5.0 (compatible; freefontpick-tools/1.0)"}

# 표의 값 → 안내문에 쓸 말. 사이트가 쓰는 말과 같아야 한다.
_ALLOW = "사용 가능"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def font_meta(font_id: int) -> dict:
    """사이트가 공개하는 값만 모은다 — 목록·라이선스·허용 표."""
    import re

    fonts = json.loads(fetch(BASE + "/api/fonts?weights=1").decode("utf-8"))
    f = next((x for x in fonts if x["id"] == font_id), None)
    if f is None:
        raise SystemExit("등록되지 않은 id: %d" % font_id)

    lic = json.loads(fetch("%s/api/fonts/%d/license" % (BASE, font_id)).decode("utf-8"))

    html = fetch("%s/font/%d" % (BASE, font_id)).decode("utf-8", "replace")
    rows, ofl = {}, ""
    m = re.search(r"(?s)<table[^>]*>(.*?)</table>", html)
    if m:
        for tr in re.findall(r"(?s)<tr>(.*?)</tr>", m.group(1)):
            th = re.search(r"(?s)<th[^>]*>(.*?)</th>", tr)
            tds = re.findall(r"(?s)<td[^>]*>(.*?)</td>", tr)
            if not th or len(tds) < 2:
                continue
            lab = re.sub(r"<[^>]+>", "", th.group(1)).strip()
            val = re.sub(r"<[^>]+>", "", tds[-1]).strip()
            if lab == "OFL":
                ofl = val
            else:
                rows[lab] = val
    return {"font": f, "lic": lic, "rows": rows, "ofl": ofl}


def _inner_name(tt) -> str:
    """폰트 파일에 적힌 영문 이름. zip 안의 파일 이름으로 쓴다.

    한글 이름을 파일명에 쓰면 압축 프로그램·운영체제에 따라 깨진다. 그렇다고
    사이트에 적힌 한글 이름에서 한글만 걷어내면 '산돌 삼립호빵체 Basic' 이
    'Basic' 이 된다. 폰트가 스스로 밝히는 이름이 가장 정확하다.
    postScript 이름(6) → 전체 이름(4) → 집안 이름(1) 순으로 본다.
    """
    try:
        rec = tt["name"]
    except Exception:
        return ""
    for nid in (6, 4, 1):
        v = rec.getDebugName(nid)
        if v:
            v = "".join(ch for ch in v if ch.isascii() and (ch.isalnum() or ch in "-_"))
            if v:
                return v
    return ""


def to_sfnt(woff2: bytes):
    """woff2 → 원래 ttf/otf 바이트, 확장자, 한글 글자 수, 파일 안의 이름."""
    tt = TTFont(io.BytesIO(woff2), fontNumber=0)
    ko = sum(1 for c in tt.getBestCmap() if 0xAC00 <= c <= 0xD7A3)
    inner = _inner_name(tt)
    tt.flavor = None                      # 압축 그릇을 벗긴다
    buf = io.BytesIO()
    tt.save(buf)
    ext = ".otf" if "CFF " in tt or "CFF2" in tt else ".ttf"
    tt.close()
    return buf.getvalue(), ext, ko, inner


def license_note(m: dict, keep: bool = False, docs=()) -> str:
    """zip 안에 넣을 안내문. 값은 전부 사이트에서 온 것이다.

    keep 이면 제작사 원본 파일을 그대로 넣은 것이라 마무리 문장이 달라진다.
    docs 에 제작사 문서가 있으면 그쪽을 정본으로 가리킨다 — 우리 안내문이
    원문보다 앞서는 것처럼 읽히면 안 된다.
    """
    f, lic, rows, ofl = m["font"], m["lic"], m["rows"], m["ofl"]
    name = f["name"]
    lines = [name, "=" * (len(name) * 2)]
    lines.append("")
    if f.get("maker"):
        lines.append("저작권자 : %s" % f["maker"])
    if lic.get("name"):
        lines.append("라이선스 : %s" % lic["name"])

    allowed = [k for k, v in rows.items() if v == _ALLOW]
    denied = [k for k, v in rows.items() if v not in (_ALLOW, "")]
    # 사이트에 아직 라이선스를 안 넣은 폰트도 있다. 그때는 빈 제목만 남는데,
    # 없는 정보를 있는 것처럼 보이게 하느니 통째로 뺀다.
    if allowed or denied or ofl:
        lines += ["", "사용 범위", "-" * 9]
        if allowed:
            lines.append("%s 에 사용할 수 있습니다." % " · ".join(allowed))
        for k in denied:
            lines.append("%s : %s" % (k, rows[k]))
        if ofl:
            lines.append("폰트 파일 수정·재배포 : %s" % ofl)

    lines += ["", "받은 곳", "-" * 7,
              "폰트픽  %s/font/%d" % (BASE, f["id"])]
    if lic.get("url"):
        lines.append("원문    %s" % lic["url"])
    lines.append("")
    if docs:
        lines += ["이 묶음에는 저작권자가 배포한 %s 가 함께 들어 있습니다."
                  % " · ".join(docs),
                  "사용 조건은 그 문서가 정본입니다. 위 내용은 참고용 요약입니다."]
    elif keep:
        lines += ["이 묶음의 폰트 파일은 제작사 원본 그대로입니다.",
                  "정확한 조건은 위 원문 주소에서 확인해 주세요."]
    else:
        lines += ["이 묶음은 폰트픽이 화면에 쓰는 파일로 만들었습니다.",
                  "제작사가 배포하는 원본 묶음과 구성이 다를 수 있으니,",
                  "정확한 조건은 위 원문 주소에서 확인해 주세요."]
    return "\r\n".join(lines) + "\r\n"


def _existing_fonts(font_id: int):
    """이미 있는 zip 안의 폰트 파일을 그대로 꺼내 온다.

    제작사가 배포한 원본 파일이 이미 묶여 있다면 그게 가장 정확하다.
    웹용 woff2 를 되돌린 파일은 글리프가 같아도 바이트가 다른데,
    '수정본 배포 금지' 가 걸린 폰트에서는 그 차이를 만들 이유가 없다.
    """
    p = OUT / ("font-%03d.zip" % font_id)
    if not p.is_file():
        return []
    out = []
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            if n.lower().endswith((".ttf", ".otf")):
                data = z.read(n)
                tt = TTFont(io.BytesIO(data), fontNumber=0, lazy=True)
                ko = sum(1 for c in tt.getBestCmap() if 0xAC00 <= c <= 0xD7A3)
                tt.close()
                out.append((n, data, 0, ko))
    return out


def build(font_id: int, check_only: bool = False, keep: bool = False) -> bool:
    m = font_meta(font_id)
    f = m["font"]
    weights = sorted(set(f.get("available_weights") or [])) or [400]

    if keep:
        files = _existing_fonts(font_id)
        if not files:
            print("   기존 zip 에 폰트 파일이 없다")
            return False
        return _write(font_id, m, files, check_only, keep=True)

    files = []
    for w in weights:
        try:
            blob = fetch("%s/api/fonts/%d/file?weight=%d" % (BASE, font_id, w))
        except urllib.error.HTTPError as e:
            print("   굵기 %d 를 못 받았다 (HTTP %s)" % (w, e.code))
            continue
        data, ext, ko, inner = to_sfnt(blob)
        files.append([inner or _ascii_stem(font_id), ext, data, w, ko])

    # 굵기 숫자는 이름이 겹칠 때만 붙인다. 대개 파일 안의 이름이 이미
    # 굵기를 밝히고 있어서(…-Bold), 무조건 붙이면 두 번 적히게 된다.
    stems = [x[0] for x in files]
    for x in files:
        if stems.count(x[0]) > 1:
            x[0] = "%s-%d" % (x[0], x[3])
    files = [(x[0] + x[1], x[2], x[3], x[4]) for x in files]

    if not files:
        print("   파일을 하나도 못 만들었다")
        return False

    return _write(font_id, m, files, check_only)


def _write(font_id: int, m: dict, files, check_only: bool, keep: bool = False) -> bool:
    for nm, data, w, ko in files:
        print("   %-28s %s%7.0fKB  한글 %d자"
              % (nm, ("굵기 %-4d " % w) if w else "          ", len(data) / 1024, ko))

    docs = sorted(p for p in (DOCS / ("font-%03d" % font_id)).glob("*")
                  if p.is_file()) if (DOCS / ("font-%03d" % font_id)).is_dir() else []
    for p in docs:
        print("   %-28s %7.0fKB  원본 문서 (바이트 그대로)" % (p.name, p.stat().st_size / 1024))
    if check_only:
        return True

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("font-%03d.zip" % font_id)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for nm, data, _w, _ko in files:
            z.writestr(nm, data)
        for p in docs:
            z.writestr(p.name, p.read_bytes())      # 다시 인코딩하지 않는다
        note = license_note(m, keep=keep, docs=[p.name for p in docs])
        z.writestr("라이선스 안내.txt", note.encode("utf-8"))
    print("   → %s  %.0fKB" % (path.name, path.stat().st_size / 1024))
    return True


def _ascii_stem(font_id: int) -> str:
    """파일 안에 이름이 없을 때의 대비책. 어느 폰트인지는 안내문에 적혀 있다."""
    return "font-%03d" % font_id


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+", type=int)
    ap.add_argument("--check", action="store_true", help="만들지 않고 확인만")
    ap.add_argument("--keep", action="store_true",
                    help="기존 zip 의 폰트 파일을 그대로 두고 문서만 새로 넣는다")
    a = ap.parse_args()

    ok = 0
    for fid in a.ids:
        print("[%d]" % fid, flush=True)
        try:
            if build(fid, a.check, a.keep):
                ok += 1
        except Exception as e:
            print("   실패: %s: %s" % (type(e).__name__, e))
    print("\n%d/%d 종 %s" % (ok, len(a.ids), "확인" if a.check else "생성"))
    return 0 if ok == len(a.ids) else 1


if __name__ == "__main__":
    sys.exit(main())
