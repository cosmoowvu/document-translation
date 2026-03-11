"""
Table Fallback Module
Handles Qwen model fallback for failed table cell translations,
and provides HTML table rebuild utility.
"""
import re
from typing import List

from app.services.translation.qwen_translator import translate_blocks_qwen, _generate_qwen
from app.services.translation.model_manager import unload_model, load_model, preload_model
from app.config import settings

_TYPHOON_MODEL = "scb10x/typhoon-translate1.5-4b:latest"


def run_qwen_cell_fallback(
    texts: List[str],
    target_lang: str,
    src_lang: str
) -> List[str]:
    """
    Fallback: Unload Typhoon → Load Qwen → Translate → Restore Typhoon.

    Args:
        texts: List of original text strings that need retranslation
        target_lang: Target language code
        src_lang: Source language code

    Returns:
        List of translated strings (same length as texts).
        Falls back to original text on per-item failure.
    """
    qwen_model = settings.FALLBACK_MODEL

    unload_model(_TYPHOON_MODEL, settings.OLLAMA_URL)
    load_model(qwen_model, settings.OLLAMA_URL)

    try:
        qwen_results, _ = translate_blocks_qwen(
            texts, target_lang, src_lang, settings.OLLAMA_URL, qwen_model
        )
    except Exception as e:
        print(f"      ⚠️ Qwen translate_blocks_qwen error: {e}")
        qwen_results = [""] * len(texts)
    finally:
        unload_model(qwen_model, settings.OLLAMA_URL)
        preload_model(_TYPHOON_MODEL, settings.OLLAMA_URL)

    # Ensure result list is same length; fall back to original where empty
    results = []
    for i, text in enumerate(texts):
        translated = qwen_results[i] if i < len(qwen_results) else ""
        results.append(translated if translated else text)

    return results


def run_qwen_raw_fallback(
    prompt: str,
    src_lang: str = None,
    target_lang: str = None
) -> str:
    """
    Fallback for raw prompt generation (e.g. OCR table → HTML).
    Unload Typhoon → Load Qwen → Generate → Restore Typhoon.

    Returns:
        Raw generated string from Qwen.
    """
    qwen_model = settings.FALLBACK_MODEL

    unload_model(_TYPHOON_MODEL, settings.OLLAMA_URL)
    load_model(qwen_model, settings.OLLAMA_URL)

    try:
        result = _generate_qwen(prompt, settings.OLLAMA_URL, qwen_model)
    except Exception as e:
        print(f"      ⚠️ Qwen _generate_qwen error: {e}")
        result = ""
    finally:
        unload_model(qwen_model, settings.OLLAMA_URL)
        preload_model(_TYPHOON_MODEL, settings.OLLAMA_URL)

    return result


def rebuild_html_table(
    original_html: str,
    cells: List[str],
    translated_cells: List[str]
) -> str:
    """
    Replace original cell contents in an HTML table with their translations.

    Args:
        original_html: The original HTML table string
        cells: List of original cell text values (in document order)
        translated_cells: Corresponding translated cell text values

    Returns:
        Rebuilt HTML string with translated cell content.
    """
    rebuilt_html = original_html

    for original, translated in zip(cells, translated_cells):
        if not original or not translated:
            continue

        escaped_original = re.escape(original)
        pattern = f'(<t[dh][^>]*>){escaped_original}(</t[dh]>)'

        def replace_func(match, t=translated):
            return match.group(1) + t + match.group(2)

        rebuilt_html = re.sub(
            pattern,
            replace_func,
            rebuilt_html,
            count=1,
            flags=re.IGNORECASE
        )

    return rebuilt_html
