"""폰트 자동 서브셋 변환

- TTF/OTF/WOFF → WOFF2 변환 + 글자 범위 축소
- 한글 폰트: KS 한글 11,172자 + ASCII + 기호
- 영문 폰트: ASCII + Latin Extended-A
- 의뢰서 3.4 사양 따름
"""
import io
import os
from typing import Tuple
from fontTools.ttLib import TTFont
from fontTools.subset import Subsetter, Options


# 한글 완성형 영역
HANGUL = list(range(0xAC00, 0xD7A4))
HANGUL_JAMO = list(range(0x1100, 0x1200)) + list(range(0x3130, 0x3190))
ASCII = list(range(0x0020, 0x007F))
LATIN1 = list(range(0x00A0, 0x0100))
LATIN_EXT_A = list(range(0x0100, 0x0180))
PUNCT = list(range(0x2000, 0x2070))
EXTRA = [
    0x00A9, 0x00AE, 0x2122, 0x00B0, 0x00B1, 0x00B7, 0x00D7, 0x00F7,
    0x2103, 0x2109, 0x203B, 0x2605, 0x2606,
    0x2661, 0x2665, 0x2660, 0x2663, 0x2666,
    0x25A0, 0x25A1, 0x25CB, 0x25CF,
    0x2192, 0x2190, 0x2191, 0x2193,
]


def get_unicodes(is_english: bool) -> list:
    base = set(ASCII + LATIN1 + PUNCT + EXTRA)
    if is_english:
        return sorted(base | set(LATIN_EXT_A))
    return sorted(base | set(HANGUL) | set(HANGUL_JAMO))


def subset_font_bytes(src_bytes: bytes, is_english: bool = False) -> Tuple[bytes, dict]:
    """폰트 바이트를 받아서 WOFF2로 서브셋 변환한 바이트와 메타 반환

    Returns:
        (woff2_bytes, info_dict)
        info_dict: {original_size, output_size, ratio}
    """
    original_size = len(src_bytes)

    # 입력을 BytesIO로
    src_io = io.BytesIO(src_bytes)
    try:
        font = TTFont(src_io)
    except Exception as e:
        raise ValueError(f"폰트 파일 로드 실패: {e}")

    options = Options()
    options.flavor = "woff2"
    options.with_zopfli = False
    options.desubroutinize = True
    options.hinting = False
    options.legacy_kern = False
    options.name_IDs = ["*"]
    options.notdef_glyph = True
    options.notdef_outline = False
    options.recommended_glyphs = True
    options.ignore_missing_glyphs = True
    options.ignore_missing_unicodes = True
    options.layout_features = ["*"]

    subsetter = Subsetter(options=options)
    unicodes = get_unicodes(is_english)
    subsetter.populate(unicodes=unicodes)

    try:
        subsetter.subset(font)
    except Exception as e:
        raise ValueError(f"서브셋 변환 실패: {e}")

    out_io = io.BytesIO()
    font.flavor = "woff2"
    try:
        font.save(out_io)
    except Exception as e:
        raise ValueError(f"WOFF2 저장 실패: {e}")

    out_bytes = out_io.getvalue()
    output_size = len(out_bytes)
    return out_bytes, {
        "original_size": original_size,
        "output_size": output_size,
        "ratio": round(output_size / original_size, 4) if original_size else 0,
        "format": "woff2",
    }
