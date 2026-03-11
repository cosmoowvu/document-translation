"""
Table Validator Module
CJK language constants and translation validation helpers for table translation.
Centralizes logic that was previously duplicated across table_translator.py
"""
import re

# CJK target languages (used for leakage scope decisions)
_CJK_LANGS = {"jpn_Jpan", "ja", "zho_Hans", "zho_Hant", "zh", "zh-cn", "kor_Hang", "ko"}


def _get_source_leakage_scripts(src_lang: str, target_lang: str) -> list:
    """
    Return regex character ranges that should NOT appear in the translated output.
    Based on the SOURCE language — we check if source chars leaked into the translation.
    Returns empty list if no leakage check is needed (e.g. English source).
    """
    # Thai source: Sarabun/Thai chars shouldn't appear in output
    if src_lang in {"tha_Thai", "th"}:
        return [r'\u0e00-\u0e7f']

    # Japanese source: Hiragana + Katakana are unique to Japanese (Kanji overlaps ZH, skip)
    if src_lang in {"jpn_Jpan", "ja"}:
        # If target is also Japanese → no check (translation is in Japanese)
        if target_lang in {"jpn_Jpan", "ja"}:
            return []
        return [r'\u3040-\u309f', r'\u30a0-\u30ff']  # Hiragana + Katakana

    # Korean source: Hangul is unique to Korean
    if src_lang in {"kor_Hang", "ko"}:
        if target_lang in {"kor_Hang", "ko"}:
            return []
        return [r'\uac00-\ud7af']

    # Chinese source: CJK Unified chars — only check when target is non-CJK
    if src_lang in {"zho_Hans", "zho_Hant", "zh", "zh-cn"}:
        if target_lang in _CJK_LANGS:
            return []  # CJK→CJK overlap too complex, handled by Qwen3 final pass
        return [r'\u4e00-\u9fff']

    # English / Latin source → no leakage concern
    return []


def check_cjk_presence(text: str, target_lang: str) -> bool:
    """
    Check if text contains characters appropriate for the CJK target language.
    Returns True if CJK characters are present (or target is not CJK).
    Returns False if target is CJK but no matching chars found.
    """
    if target_lang not in _CJK_LANGS:
        return True  # Not a CJK target — no check needed

    clean_text = re.sub(r'<[^>]+>', '', text)  # Strip HTML tags

    if target_lang in {"jpn_Jpan", "ja"}:
        return any('\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff' for c in clean_text)
    elif target_lang in {"zho_Hans", "zho_Hant", "zh", "zh-cn"}:
        return any('\u4e00' <= c <= '\u9fff' for c in clean_text)
    elif target_lang in {"kor_Hang", "ko"}:
        return any('\uac00' <= c <= '\ud7af' for c in clean_text)

    return True


def validate_translation(
    original: str,
    translated: str,
    src_lang: str,
    target_lang: str,
    cell_num: int = None
) -> bool:
    """
    Validate a single translated string.
    Returns True if translation is acceptable, False if it needs Qwen fallback.

    Checks:
      1. Technical failure (empty result)
      2. Source language leakage (source script chars present in output)
      3. CJK target presence (output must contain CJK chars when target is CJK)
    """
    label = f"Cell {cell_num}" if cell_num is not None else "Text"

    # Check 1: Empty result
    if not translated or not translated.strip():
        return False

    # Check 2: Source language leakage
    forbidden_scripts = _get_source_leakage_scripts(src_lang, target_lang)
    if forbidden_scripts:
        for script_range in forbidden_scripts:
            if re.search(f'[{script_range}]', translated):
                print(f"      ⚠️ {label}: Source leakage detected ({src_lang})")
                return False

    # Check 3: CJK target presence
    if target_lang in _CJK_LANGS:
        clean_text = re.sub(r'<[^>]+>', '', translated)
        if not check_cjk_presence(clean_text, target_lang) and len(clean_text.strip()) > 0:
            # Only fail if original had meaningful (alphanumeric) text
            if any(c.isalnum() for c in original):
                print(f"      ⚠️ {label}: No {target_lang} characters in output (Translation failed)")
                return False

    return True
