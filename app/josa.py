"""주격 조사 '이/가' 고르기 (2026-10-07).

조합 설명(app/routers/pairings.py _describe)이 폰트 이름·한 줄 설명 뒤에 늘 '가'를 붙였다.
그래서 '에스코어드림가'·'…제목용 고딕가' 처럼 틀린 문장이 3,060개 중 794개 나왔다.
폰트 이름은 한글·영문·숫자가 섞여 있어서, 마지막 글자를 읽는 소리로 받침을 가린다.

    한글   받침이 있으면 '이'
    숫자   마지막 숫자를 읽은 소리. 0(영·십·백·천)·1(일)·3(삼)·6(육)·7(칠)·8(팔)은 받침
    영문   끝이 대문자 세 자 이하 약자(KR·SC·XT)면 글자 이름으로 읽는다. L 엘·M 엠·N 엔·R 알만 받침
           나머지는 외래어 표기법의 끝소리를 따른다.
           l·m·n·ng 은 받침이다(신젤·슬림·모노톤·코딩).
           짧은 모음 뒤 k·c·t·p 는 받침이다(루빅·고딕·아웃핏·팝).
           b·d·g·s·f·r·모음은 받침이 없다(가라몬드·산스·세리프·인터).
           묵음 e 는 앞 자음으로 본다(가브리엘·맨로프).
    괄호   '송명 (Song Myung)'·'Diphylleia (산하엽)' 처럼 끝에 붙은 괄호 풀이는 떼고 앞말로 본다

영어 발음을 규칙으로 다 잡을 수는 없다. 그래서 운영 데이터(폰트 이름 534종·조합 3,060개)에서
규칙이 틀린 이름만 _EXCEPTIONS 에 적어 둔다.
"""
import re
import unicodedata

# 끝에 붙은 괄호 풀이 — 반각·전각 괄호 모두
_TRAILING_PAREN = re.compile(r"\s*[(\[（［][^()\[\]（）［］]*[)\]）］]\s*$")
_BATCHIM_DIGITS = set("013678")
_BATCHIM_LETTERS = set("LMNR")
_VOWELS = set("aeiou")

# 규칙이 틀리는 영어 단어 — 소문자 단어: 받침 여부
_EXCEPTIONS = {
    "caveat": True,   # 캐비엇
}


def _english_word_has_batchim(word: str) -> bool:
    w = word.lower()
    if w in _EXCEPTIONS:
        return _EXCEPTIONS[w]
    if w.endswith("ng"):
        return True
    # 묵음 e — line 라인·time 타임·noble 노블 / rope 로프·write 라이트
    if len(w) >= 3 and w[-1] == "e" and w[-2] not in _VOWELS and w[-2] != "y":
        return w[-2] in "lmn"
    last = w[-1]
    if last in "lmn":
        return True
    if w.endswith("ck"):
        return True
    if last in "kctp" and len(w) >= 2 and w[-2] in _VOWELS:
        # 짧은 모음(모음 글자 하나) 뒤에서만 받침 — cut 컷·magic 매직 / boat 보트·beat 비트
        # 단 oo 는 짧게 읽는 일이 많다 — book 북·look 룩
        if len(w) >= 3 and w[-3] in _VOWELS:
            return w[-3:-1] == "oo" and last == "k"
        return True
    return False


def has_batchim(word: str):
    """받침으로 끝나면 True, 아니면 False. 판단할 글자가 없으면 None."""
    w = (word or "").strip()
    while True:
        cut = _TRAILING_PAREN.sub("", w)
        if cut == w or not cut:
            break
        w = cut
    w = w.rstrip(" '\"’”」』.,·…!?~")
    if not w:
        return None
    ch = w[-1]
    code = ord(ch)
    if 0xAC00 <= code <= 0xD7A3:
        return (code - 0xAC00) % 28 != 0
    if ch.isdigit():
        return ch in _BATCHIM_DIGITS
    try:
        num = unicodedata.numeric(ch)   # Ⅱ·② 처럼 숫자로 읽는 글자
    except (TypeError, ValueError):
        num = None
    if num is not None:
        if float(num).is_integer():
            return str(int(num))[-1] in _BATCHIM_DIGITS
        return None
    if ch.isascii() and ch.isalpha():
        token = re.search(r"[A-Za-z]+$", w).group(0)
        caps = re.search(r"[A-Z]*$", token).group(0)
        # 끝이 대문자 약자(KR·SC·IBM·BodoniXT 의 XT) — 글자 이름으로 읽는다.
        # 대문자만 네 자 이상(SUPER·SERIF)은 단어로 읽는다.
        if caps and len(caps) <= 3 and (len(caps) == len(token) or token[-len(caps) - 1].islower()):
            return caps[-1] in _BATCHIM_LETTERS
        return _english_word_has_batchim(token)
    return None


def i_ga(word: str) -> str:
    """word 뒤에 붙일 주격 조사. 받침을 모르면 '가'(예전 그대로)."""
    return "이" if has_batchim(word) else "가"
