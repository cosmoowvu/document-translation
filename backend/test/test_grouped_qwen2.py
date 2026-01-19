"""
PDF Translation: Docling-based OCR (v2.0)
- ใช้ Docling สำหรับ OCR ที่แม่นยำ
- ใช้ NLLB-CT2 แปล (เร็ว, แม่นยำ)
- ใช้ Qwen2.5 refine ให้ natural
"""
import os
import sys
import time
import requests
import re
import unicodedata
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from PIL import Image, ImageDraw, ImageFont
from docling.document_converter import DocumentConverter
from docling_core.types.doc import DocItemLabel

# NLLB-CT2
import ctranslate2
from transformers import AutoTokenizer

# ===== ตั้งค่า =====
PDF_PATH = "./test6.docx"
OUTPUT_DIR = "./output_images/pdf_docling"
DPI = 150

# Ollama settings (for refinement)
OLLAMA_URL = "http://localhost:11434/api/generate"
QWEN_MODEL = "qwen2.5:1.5b"

# NLLB-CT2 settings
NLLB_MODEL_DIR = "../models/nllb-1.3b-ct2"
NLLB_TOKENIZER = "facebook/nllb-200-1.3B"

# Font - เลือกตามภาษา
FONT_PATHS = {
    "tha_Thai": "C:/Windows/Fonts/tahoma.ttf",      # Thai
    "zho_Hans": "C:/Windows/Fonts/msyh.ttc",        # Chinese Simplified
    "zho_Hant": "C:/Windows/Fonts/msyh.ttc",        # Chinese Traditional
    "jpn_Jpan": "C:/Windows/Fonts/msgothic.ttc",    # Japanese
    "kor_Hang": "C:/Windows/Fonts/malgun.ttf",      # Korean
    "default": "C:/Windows/Fonts/arial.ttf",        # Default
}
CURRENT_FONT_PATH = FONT_PATHS["default"]  # จะถูก set ตาม target language

# Debug
DEBUG = True
LOG_DIR = "./output_images/pdf_docling/logs"

# Timing
total_translation_time = 0

# ===== Load NLLB Model =====
print("📥 กำลังโหลด NLLB-CT2...")
nllb_tokenizer = AutoTokenizer.from_pretrained(NLLB_TOKENIZER)
nllb_device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
nllb_translator = ctranslate2.Translator(NLLB_MODEL_DIR, device=nllb_device, compute_type="int8")
print(f"✅ NLLB พร้อม ({nllb_device.upper()})")


def get_font(size=16, tgt_lang=None):
    global CURRENT_FONT_PATH
    
    # เลือก font ตาม target language
    if tgt_lang:
        font_path = FONT_PATHS.get(tgt_lang, FONT_PATHS["default"])
    else:
        font_path = CURRENT_FONT_PATH
    
    if os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except:
            pass
    
    # Fallback
    for path in FONT_PATHS.values():
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                continue
    
    return ImageFont.load_default()


def normalize_ocr_text(text: str) -> str:
    """
    Normalize ข้อความหลัง OCR
    แก้ไขอักขระพิเศษที่ OCR มักอ่านผิด
    """
    import unicodedata
    
    if not text:
        return text
    
    # 1. Unicode normalization (NFC - Composed form)
    text = unicodedata.normalize('NFC', text)
    
    # 2. Quotes & Apostrophes
    quote_replacements = {
        '"': '"', '"': '"',     # Smart double quotes → straight
        '„': '"', '‟': '"',     # German/Eastern quotes
        '«': '"', '»': '"',     # Guillemets
        '‹': "'", '›': "'",     # Single guillemets
        ''': "'", ''': "'",     # Smart single quotes → straight
        '‛': "'", '`': "'",     # Other apostrophes
        '′': "'", '″': '"',     # Prime symbols
    }
    
    # 3. Dashes & Hyphens
    dash_replacements = {
        '—': '-',   # Em dash
        '–': '-',   # En dash
        '‒': '-',   # Figure dash
        '―': '-',   # Horizontal bar
        '⁃': '-',   # Hyphen bullet
        '‐': '-',   # Hyphen
        '‑': '-',   # Non-breaking hyphen
        '−': '-',   # Minus sign
    }
    
    # 4. Spaces
    space_replacements = {
        '\xa0': ' ',    # Non-breaking space
        '\u2000': ' ',  # En quad
        '\u2001': ' ',  # Em quad
        '\u2002': ' ',  # En space
        '\u2003': ' ',  # Em space
        '\u2004': ' ',  # Three-per-em space
        '\u2005': ' ',  # Four-per-em space
        '\u2006': ' ',  # Six-per-em space
        '\u2007': ' ',  # Figure space
        '\u2008': ' ',  # Punctuation space
        '\u2009': ' ',  # Thin space
        '\u200a': ' ',  # Hair space
        '\u200b': '',   # Zero-width space (remove)
        '\u200c': '',   # Zero-width non-joiner (remove)
        '\u200d': '',   # Zero-width joiner (remove)
        '\u202f': ' ',  # Narrow no-break space
        '\u205f': ' ',  # Medium mathematical space
        '\u3000': ' ',  # Ideographic space
        '\ufeff': '',   # BOM / Zero-width no-break space (remove)
    }
    
    # 5. Dots & Ellipsis
    dot_replacements = {
        '…': '...',     # Ellipsis → three dots
        '⋯': '...',     # Midline ellipsis
        '‥': '..',      # Two dot leader
        '․': '.',       # One dot leader
        '·': '.',       # Middle dot → period
        '•': '-',       # Bullet → dash
        '◦': '-',       # White bullet
        '‣': '-',       # Triangular bullet
        '⁃': '-',       # Hyphen bullet
    }
    
    # 6. Ligatures
    ligature_replacements = {
        'ﬁ': 'fi',
        'ﬂ': 'fl',
        'ﬀ': 'ff',
        'ﬃ': 'ffi',
        'ﬄ': 'ffl',
        'ﬅ': 'st',
        'ﬆ': 'st',
        'Ĳ': 'IJ', 'ĳ': 'ij',
        'Œ': 'OE', 'œ': 'oe',
        'Æ': 'AE', 'æ': 'ae',
    }
    
    # 7. Fractions
    fraction_replacements = {
        '½': '1/2', '⅓': '1/3', '⅔': '2/3',
        '¼': '1/4', '¾': '3/4',
        '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
        '⅙': '1/6', '⅚': '5/6',
        '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
    }
    
    # 8. Symbols
    symbol_replacements = {
        '™': '(TM)',
        '®': '(R)',
        '©': '(C)',
        '℗': '(P)',
        '№': 'No.',
        '℃': 'C',
        '℉': 'F',
        '°': ' degrees ',
        '±': '+/-',
        '×': 'x',
        '÷': '/',
        '≈': '~',
        '≠': '!=',
        '≤': '<=',
        '≥': '>=',
        '←': '<-',
        '→': '->',
        '↔': '<->',
        '⇐': '<=',
        '⇒': '=>',
    }
    
    # 9. Currency (keep as text)
    currency_replacements = {
        '฿': 'THB ',
        '€': 'EUR ',
        '£': 'GBP ',
        '¥': 'JPY ',
        '₩': 'KRW ',
        '₹': 'INR ',
        '₽': 'RUB ',
    }
    
    # 10. Superscripts & Subscripts
    script_replacements = {
        '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4',
        '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9',
        '₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4',
        '₅': '5', '₆': '6', '₇': '7', '₈': '8', '₉': '9',
    }
    
    # Apply all replacements
    all_replacements = {}
    all_replacements.update(quote_replacements)
    all_replacements.update(dash_replacements)
    all_replacements.update(space_replacements)
    all_replacements.update(dot_replacements)
    all_replacements.update(ligature_replacements)
    all_replacements.update(fraction_replacements)
    all_replacements.update(symbol_replacements)
    all_replacements.update(currency_replacements)
    all_replacements.update(script_replacements)
    
    for old, new in all_replacements.items():
        text = text.replace(old, new)
    
    # 11. Remove control characters (except newline, tab)
    text = ''.join(c for c in text if c in '\n\t' or not unicodedata.category(c).startswith('C'))
    
    # 12. Collapse multiple spaces
    text = re.sub(r' +', ' ', text)
    
    return text.strip()

def detect_language(text: str) -> str:
    """
    ตรวจจับภาษาหลักของข้อความ
    รองรับ: ไทย, ญี่ปุ่น, จีน, เกาหลี, อังกฤษ (default)
    """
    if not text:
        return "unknown"
    
    # นับตัวอักษรแต่ละภาษา
    thai = sum(1 for c in text if '\u0e00' <= c <= '\u0e7f')
    japanese = sum(1 for c in text if '\u3040' <= c <= '\u30ff')  # Hiragana + Katakana
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')   # CJK
    korean = sum(1 for c in text if '\uac00' <= c <= '\ud7af')    # Hangul
    
    total = len(text.replace(" ", ""))
    if total == 0:
        return "unknown"
    
    # หาภาษาที่มีสัดส่วนสูงสุด (threshold 20%)
    lang_ratios = {
        "tha_Thai": thai / total,
        "jpn_Jpan": japanese / total,
        "zho_Hans": chinese / total,
        "kor_Hang": korean / total
    }
    
    max_lang = max(lang_ratios, key=lang_ratios.get)
    if lang_ratios[max_lang] > 0.2:
        return max_lang
    
    return "eng_Latn"  # default = English


def should_translate(text: str, target_lang: str):
    """
    ตรวจว่า block นี้ต้องแปลไหม
    Returns: (should_translate, detected_language)
    """
    detected = detect_language(text)
    
    # ถ้าเป็นภาษาเป้าหมายอยู่แล้ว → ไม่ต้องแปล
    if detected == target_lang:
        return False, detected
    
    return True, detected


def translate_with_nllb(text: str, src_lang: str, tgt_lang: str) -> str:
    """
    แปลข้อความด้วย NLLB-CT2 (เร็ว, แม่นยำ)
    """
    global total_translation_time
    
    if not text or len(text.strip()) < 2:
        return text
    
    start = time.time()
    
    try:
        nllb_tokenizer.src_lang = src_lang
        tokens = nllb_tokenizer.convert_ids_to_tokens(nllb_tokenizer.encode(text))
        
        result = nllb_translator.translate_batch(
            [tokens],
            target_prefix=[[tgt_lang]],
            beam_size=5,
        )
        
        target_tokens = result[0].hypotheses[0][1:]  # skip language token
        translated = nllb_tokenizer.decode(nllb_tokenizer.convert_tokens_to_ids(target_tokens))
        
        total_translation_time += (time.time() - start)
        return translated
        
    except Exception as e:
        if DEBUG:
            print(f"      ⚠️ NLLB error: {e}")
        return text


def translate_batch_nllb(texts: list, src_lang: str, tgt_lang: str) -> list:
    """
    แปลหลาย texts พร้อมกันด้วย NLLB-CT2 (batch processing)
    เร็วกว่าแปลทีละอัน
    """
    global total_translation_time
    
    if not texts:
        return []
    
    results = [""] * len(texts)
    to_translate = []
    translate_indices = []
    
    # แยก texts ที่ต้องแปลจริงๆ
    for i, text in enumerate(texts):
        if not text or len(text.strip()) < 2:
            results[i] = text
        else:
            to_translate.append(text)
            translate_indices.append(i)
    
    if not to_translate:
        return results
    
    start = time.time()
    
    try:
        nllb_tokenizer.src_lang = src_lang
        
        # Tokenize ทุก texts
        all_tokens = []
        for text in to_translate:
            tokens = nllb_tokenizer.convert_ids_to_tokens(nllb_tokenizer.encode(text))
            all_tokens.append(tokens)
        
        # Batch translate
        target_prefixes = [[tgt_lang]] * len(all_tokens)
        batch_results = nllb_translator.translate_batch(
            all_tokens,
            target_prefix=target_prefixes,
            beam_size=5,
        )
        
        # Decode results
        for i, result in enumerate(batch_results):
            target_tokens = result.hypotheses[0][1:]  # skip language token
            translated = nllb_tokenizer.decode(nllb_tokenizer.convert_tokens_to_ids(target_tokens))
            original_idx = translate_indices[i]
            results[original_idx] = translated
        
        total_translation_time += (time.time() - start)
        
    except Exception as e:
        if DEBUG:
            print(f"      ⚠️ NLLB batch error: {e}")
        # Fallback: ใส่ต้นฉบับกลับ
        for i, idx in enumerate(translate_indices):
            results[idx] = to_translate[i]
    
    return results


def refine_with_qwen(original: str, nllb_translation: str, tgt_lang: str) -> str:
    """
    ใช้ Qwen2.5 ปรับปรุง NLLB translation ให้ natural ขึ้น
    """
    global total_translation_time
    
    if not nllb_translation or len(nllb_translation.strip()) < 5:
        return nllb_translation
    
    if tgt_lang == "eng_Latn":
        prompt = f"""Improve this machine translation to be more natural and fluent.
Keep the same meaning and all numbers/formatting.
Output ONLY the improved text, no explanations.

Original (Thai): {original}
Machine Translation: {nllb_translation}
Improved:"""
    else:
        prompt = f"""ปรับปรุงการแปลนี้ให้เป็นธรรมชาติมากขึ้น
คงความหมายและตัวเลข/รูปแบบเดิมไว้
ตอบเฉพาะข้อความที่ปรับปรุงแล้ว ไม่ต้องอธิบาย

Original (English): {original}
Machine Translation: {nllb_translation}
Improved:"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": QWEN_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512}
            },
            timeout=60
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            result = resp.json().get("response", "").strip()
            # ลบ markdown formatting
            result = re.sub(r'^\*+|\*+$', '', result)
            # ตรวจสอบว่าไม่ใช่ prompt
            if "Improved:" in result or "translation" in result.lower():
                return nllb_translation
            if len(result) > 0:
                return result
                
    except Exception as e:
        if DEBUG:
            print(f"      ⚠️ Qwen refine error: {e}")
    
    return nllb_translation  # fallback to NLLB result


def refine_batch_with_qwen(originals: list, nllb_translations: list, tgt_lang: str) -> list:
    """
    Qwen ตรวจสอบ NLLB translation - แก้เฉพาะที่จำเป็น
    Output: GOOD (ใช้ NLLB เลย) หรือ FIX: [แก้ไขแล้ว]
    """
    global total_translation_time
    
    if not nllb_translations:
        return []
    
    results = nllb_translations.copy()
    
    # สร้าง prompt รวม
    lines = []
    valid_indices = []
    for idx, (orig, nllb) in enumerate(zip(originals, nllb_translations)):
        if nllb and len(nllb.strip()) >= 5:
            lines.append(f"###ITEM{idx+1}###\nOriginal: {orig}\nTranslation: {nllb}")
            valid_indices.append(idx)
    
    if not lines:
        return results
    
    combined = "\n\n".join(lines)
    
    if tgt_lang == "eng_Latn":
        prompt = f"""Check these machine translations. For each item:
- If the translation is ALREADY GOOD, respond: ###ITEMX### GOOD
- If it needs improvement, respond: ###ITEMX### FIX: [improved translation]

Only fix translations that have grammatical errors, unnatural phrasing, or incorrect meaning.
Keep all numbers and formatting.

{combined}

Your evaluation:"""
    else:
        prompt = f"""ตรวจสอบการแปลเหล่านี้ สำหรับแต่ละ item:
- ถ้าแปลได้ดีแล้ว ตอบ: ###ITEMX### GOOD
- ถ้าต้องปรับปรุง ตอบ: ###ITEMX### FIX: [ข้อความที่แก้ไขแล้ว]

แก้เฉพาะที่มีปัญหาไวยากรณ์ สำนวนไม่ธรรมชาติ หรือความหมายผิด
คงตัวเลขและรูปแบบเดิมไว้

{combined}

การประเมินของคุณ:"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": QWEN_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 4096}
            },
            timeout=180
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            response = resp.json().get("response", "").strip()
            
            # Count stats
            good_count = 0
            fix_count = 0
            
            # Parse response
            pattern = r'###ITEM(\d+)###\s*(GOOD|FIX:\s*(.+?))(?=###ITEM\d+###|$)'
            matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
            
            for num_str, status, fix_text in matches:
                idx = int(num_str) - 1
                if 0 <= idx < len(results):
                    if status.upper().startswith("GOOD"):
                        good_count += 1
                        # Keep NLLB result (already in results)
                    elif fix_text:
                        cleaned = fix_text.strip()
                        cleaned = re.sub(r'^\*+|\*+$', '', cleaned)
                        if cleaned and len(cleaned) > 3:
                            results[idx] = cleaned
                            fix_count += 1
            
            if DEBUG:
                print(f"         📊 GOOD: {good_count}, FIX: {fix_count}")
                        
    except Exception as e:
        if DEBUG:
            print(f"      ⚠️ Qwen check error: {e}")
    
    return results


def translate_nllb_qwen(text: str, src_lang: str, tgt_lang: str) -> str:
    """
    Pipeline: NLLB แปล → Qwen2.5 refine
    """
    # Step 1: NLLB translate
    nllb_result = translate_with_nllb(text, src_lang, tgt_lang)
    
    # Step 2: Qwen2.5 refine
    refined = refine_with_qwen(text, nllb_result, tgt_lang)
    
    return refined


# Stats tracking
translation_stats = {"translated": 0, "skipped": 0}


def translate_text(text: str, tgt_lang: str) -> tuple:
    """
    แปลข้อความด้วย Qwen2.5
    Returns: (translated_text, detected_lang, was_translated)
    """
    global total_translation_time, translation_stats
    
    if not text or len(text.strip()) < 2:
        return text, "unknown", False
    
    # ตรวจจับภาษาก่อน
    need_translate, detected_lang = should_translate(text, tgt_lang)
    
    if not need_translate:
        # ข้าม - เป็นภาษาเป้าหมายแล้ว
        translation_stats["skipped"] += 1
        if DEBUG:
            print(f"      ⏭️ SKIP: เป็น {detected_lang} อยู่แล้ว")
        return text, detected_lang, False
    
    if tgt_lang == "eng_Latn":
        prompt = f"""Translate to English. Output ONLY the translation, no explanations.

{text}"""
    else:
        prompt = f"""Translate to Thai. Output ONLY the translation, no explanations.

{text}"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": QWEN_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1024}
            },
            timeout=120
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            result = resp.json().get("response", "").strip()
            # ลบ prefix ที่ model อาจใส่มา
            result = re.sub(r'^(Translation:|English:|Thai:)\s*', '', result, flags=re.IGNORECASE)
            translation_stats["translated"] += 1
            return result.strip(), detected_lang, True
            
    except Exception as e:
        print(f"   ⚠️ Translation error: {e}")
    
    return text, detected_lang, False


def translate_page_blocks(blocks: list, tgt_lang: str) -> list:
    """
    แปล blocks ด้วย Qwen2.5 (batch 5) + fallback chain:
    1. Qwen2.5 batch (5 blocks)
    2. ถ้าไม่ได้ → Qwen2.5 retry ทีละ block
    3. ถ้ายังไม่ได้ → NLLB fallback
    4. ถ้ายังไม่ได้ → return ต้นฉบับ
    """
    global translation_stats
    
    if not blocks:
        return blocks
    
    BATCH_SIZE = 5
    
    # แยก blocks ที่ต้องแปล vs ไม่ต้องแปล
    to_translate = []
    already_target = []
    
    for i, block in enumerate(blocks):
        text = normalize_ocr_text(block['text'])
        need_translate, detected_lang = should_translate(text, tgt_lang)
        
        if need_translate:
            to_translate.append((i, block, text, detected_lang))
        else:
            already_target.append((i, block, text, detected_lang))
            translation_stats["skipped"] += 1
    
    # เตรียม results
    results = [None] * len(blocks)
    
    # ใส่ blocks ที่ไม่ต้องแปล
    for i, block, text, detected_lang in already_target:
        results[i] = {
            **block,
            'translated': text,
            'detected_lang': detected_lang,
            'was_translated': False
        }
    
    if not to_translate:
        return results
    
    # คำนวณ batches
    num_batches = (len(to_translate) + BATCH_SIZE - 1) // BATCH_SIZE
    
    if DEBUG:
        print(f"      📊 ต้องแปล: {len(to_translate)}, ข้าม: {len(already_target)}, batches: {num_batches}")
    
    # แปลแต่ละ batch ด้วย Qwen2.5
    for batch_idx in range(num_batches):
        start_idx = batch_idx * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, len(to_translate))
        batch = to_translate[start_idx:end_idx]
        
        if DEBUG:
            print(f"      🔄 Batch {batch_idx + 1}/{num_batches} ({len(batch)} blocks)")
        
        # Step 1: Qwen2.5 batch translate
        batch_results = translate_batch_qwen(batch, tgt_lang)
        
        # ใส่ผลลัพธ์
        for j, (i, block, text, detected_lang) in enumerate(batch):
            translated = batch_results[j] if j < len(batch_results) else None
            
            # ตรวจสอบผลลัพธ์
            if translated and translated != text:
                # Post-process: แก้ไขตัวเลขนำหน้า
                translated = fix_number_prefix(text, translated, tgt_lang)
                translation_stats["translated"] += 1
            else:
                translated = text  # fallback to original
                translation_stats["translated"] += 1
            
            results[i] = {
                **block,
                'translated': translated,
                'detected_lang': detected_lang,
                'was_translated': True
            }
    
    return results


def translate_batch_qwen(batch: list, tgt_lang: str) -> list:
    """
    แปล batch ด้วย Qwen2.5 + fallback chain:
    1. Qwen2.5 batch
    2. Qwen2.5 retry (ทีละอัน)
    3. NLLB fallback
    4. Original fallback
    """
    global total_translation_time
    
    if not batch:
        return []
    
    original_texts = [text for (i, block, text, detected_lang) in batch]
    results = [''] * len(batch)
    
    # หา source language
    src_lang = batch[0][3] if batch[0][3] != "unknown" else "tha_Thai"
    
    # สร้าง prompt
    lines_text = []
    for idx, (i, block, text, detected_lang) in enumerate(batch):
        lines_text.append(f"###BLOCK{idx + 1}### {text}")
    
    combined_text = "\n".join(lines_text)
    
    # Map NLLB language codes to language names
    lang_names = {
        "eng_Latn": "English",
        "tha_Thai": "Thai",
        "zho_Hans": "Chinese (Simplified)",
        "zho_Hant": "Chinese (Traditional)",
        "jpn_Jpan": "Japanese",
        "kor_Hang": "Korean",
        "vie_Latn": "Vietnamese",
        "fra_Latn": "French",
        "deu_Latn": "German",
        "spa_Latn": "Spanish",
    }
    target_name = lang_names.get(tgt_lang, tgt_lang)
    
    prompt = f"""Translate each line to {target_name} ONLY. Keep the ###BLOCKX### markers exactly as they are.
CRITICAL: Output ONLY {target_name} language. Do NOT mix Chinese or other languages.
IMPORTANT: Preserve all numbers and formatting from the original text.
IMPORTANT: For technical terms, proper nouns, and specialized vocabulary, keep them in English or transliterate them (do NOT translate literally).
Examples: "Machine Learning" → "Machine Learning", "Deep Learning" → "Deep Learning"
Output ONLY the translations with their markers, no explanations.

{combined_text}"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": QWEN_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2048}
            },
            timeout=120
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            response = resp.json().get("response", "").strip()
            
            # Parse response
            translated_lines = parse_marker_response(response, len(batch), original_texts)
            
            # ตรวจสอบและ fallback ถ้าไม่ผ่าน
            failed_indices = []
            for idx, translated in enumerate(translated_lines):
                is_valid, reason = validate_translation(original_texts[idx], translated, tgt_lang)
                if is_valid:
                    results[idx] = translated
                else:
                    failed_indices.append(idx)
                    if DEBUG:
                        print(f"         ⚠️ Block {idx+1} invalid ({reason}), will retry")
            
            # Step 2: Qwen2.5 retry ทีละอัน
            if failed_indices:
                if DEBUG:
                    print(f"         🔄 Retrying {len(failed_indices)} blocks with Qwen...")
                
                for idx in failed_indices:
                    text = original_texts[idx]
                    retry_result = translate_single_qwen(text, tgt_lang)
                    
                    is_valid, reason = validate_translation(text, retry_result, tgt_lang)
                    if is_valid:
                        results[idx] = retry_result
                        if DEBUG:
                            print(f"         ✅ Block {idx+1} Qwen retry success")
                    else:
                        # Step 3: NLLB fallback
                        if DEBUG:
                            print(f"         📦 Block {idx+1} trying NLLB...")
                        nllb_result = translate_with_nllb(text, src_lang, tgt_lang)
                        
                        is_valid, reason = validate_translation(text, nllb_result, tgt_lang)
                        if is_valid:
                            results[idx] = nllb_result
                            if DEBUG:
                                print(f"         ✅ Block {idx+1} NLLB success")
                        else:
                            # Step 4: ถ้า NLLB ยังไม่ผ่าน (เช่น too long) ก็ใช้ NLLB ไปเลย
                            # เพราะ NLLB แม่นยำกว่า original ที่เป็นภาษาต้นทาง
                            if nllb_result and len(nllb_result.strip()) > 0:
                                results[idx] = nllb_result
                                if DEBUG:
                                    print(f"         ⚠️ Block {idx+1} use NLLB anyway ({reason})")
                            else:
                                results[idx] = text
                                if DEBUG:
                                    print(f"         ❌ Block {idx+1} use original")
            
            return results
            
    except Exception as e:
        if DEBUG:
            print(f"      ⚠️ Batch translation error: {e}")
    
    # Fallback: แปลทีละ block
    if DEBUG:
        print(f"      🔄 Batch failed, trying block-by-block...")
    
    for idx, (i, block, text, detected_lang) in enumerate(batch):
        # Try Qwen
        result = translate_single_qwen(text, tgt_lang)
        is_valid, _ = validate_translation(text, result, tgt_lang)
        
        if is_valid:
            results[idx] = result
        else:
            # Try NLLB
            src_lang = detected_lang if detected_lang != "unknown" else "tha_Thai"
            nllb_result = translate_with_nllb(text, src_lang, tgt_lang)
            # ใช้ NLLB result ไปเลย ไม่ว่าจะ validate ผ่านหรือไม่
            results[idx] = nllb_result if nllb_result else text
    
    return results


def translate_single_qwen(text: str, tgt_lang: str) -> str:
    """แปลข้อความเดียวด้วย Qwen2.5 (สำหรับ retry)"""
    global total_translation_time
    
    if not text or len(text.strip()) < 2:
        return text
    
    if tgt_lang == "eng_Latn":
        prompt = f"""Translate to English. Preserve all numbers and formatting.
For technical terms and proper nouns, keep them in original form.
Output ONLY the translation, no explanations.

{text}"""
    else:
        prompt = f"""Translate to Thai. Preserve all numbers and formatting.
For technical terms and proper nouns, keep them in English or transliterate (do NOT translate literally).
Output ONLY the translation, no explanations.

{text}"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": QWEN_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512}
            },
            timeout=60
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            result = resp.json().get("response", "").strip()
            result = re.sub(r'^\*+|\*+$', '', result)
            return result
            
    except Exception as e:
        if DEBUG:
            print(f"         ⚠️ Single Qwen error: {e}")
    
    return ""  # Return empty to trigger fallback


def translate_batch(batch: list, tgt_lang: str) -> list:
    """
    แปล batch ของ blocks (ไม่เกิน 5 blocks)
    ถ้าแปลไม่ครบจะ retry ทีละ block
    Returns: list ของผลลัพธ์การแปล
    """
    global total_translation_time
    
    if not batch:
        return []
    
    original_texts = [text for (i, block, text, detected_lang) in batch]
    results = [''] * len(batch)
    
    # สร้าง prompt
    lines_text = []
    for idx, (i, block, text, detected_lang) in enumerate(batch):
        lines_text.append(f"###BLOCK{idx + 1}### {text}")
    
    combined_text = "\n".join(lines_text)
    
    if tgt_lang == "eng_Latn":
        prompt = f"""Translate each line to English. Keep the ###BLOCKX### markers exactly as they are.
IMPORTANT: Preserve all numbers and formatting from the original text.
Output ONLY the translations with their markers, no explanations.

{combined_text}"""
    else:
        prompt = f"""Translate each line to Thai. Keep the ###BLOCKX### markers exactly as they are.
IMPORTANT: Preserve all numbers and formatting from the original text.
Output ONLY the translations with their markers, no explanations.

{combined_text}"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": QWEN_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2048}
            },
            timeout=120
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            response = resp.json().get("response", "").strip()
            
            # Parse response
            translated_lines = parse_marker_response(response, len(batch), original_texts)
            
            # ตรวจสอบและ retry ถ้าไม่ผ่าน validation
            failed_indices = []
            for idx, translated in enumerate(translated_lines):
                is_valid, reason = validate_translation(original_texts[idx], translated, tgt_lang)
                if is_valid:
                    results[idx] = translated
                else:
                    failed_indices.append(idx)
                    if DEBUG:
                        print(f"         ⚠️ Block {idx+1} invalid ({reason}), will retry")
            
            # Retry failed blocks ทีละอัน
            if failed_indices:
                if DEBUG:
                    print(f"         🔄 Retrying {len(failed_indices)} failed blocks...")
                
                for idx in failed_indices:
                    i, block, text, detected_lang = batch[idx]
                    retry_result = translate_single_block(text, tgt_lang)
                    
                    # Validate retry result
                    is_valid, reason = validate_translation(text, retry_result, tgt_lang)
                    if is_valid:
                        results[idx] = retry_result
                        if DEBUG:
                            print(f"         ✅ Block {idx+1} retry success")
                    else:
                        results[idx] = text  # Final fallback to original
                        if DEBUG:
                            print(f"         ❌ Block {idx+1} retry failed, use original")
            
            return results
            
    except Exception as e:
        if DEBUG:
            print(f"      ⚠️ Batch translation error: {e}")
    
    # Fallback: แปลทีละ block
    if DEBUG:
        print(f"      🔄 Batch failed, trying block-by-block...")
    
    for idx, (i, block, text, detected_lang) in enumerate(batch):
        retry_result = translate_single_block(text, tgt_lang)
        is_valid, reason = validate_translation(text, retry_result, tgt_lang)
        results[idx] = retry_result if is_valid else text
    
    return results


def translate_single_block(text: str, tgt_lang: str) -> str:
    """แปลข้อความเดียว (สำหรับ retry)"""
    global total_translation_time
    
    if not text or len(text.strip()) < 2:
        return text
    
    if tgt_lang == "eng_Latn":
        prompt = f"""Translate to English. Preserve all numbers and formatting.
Output ONLY the translation, no explanations.

{text}"""
    else:
        prompt = f"""Translate to Thai. Preserve all numbers and formatting.
Output ONLY the translation, no explanations.

{text}"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": QWEN_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512}
            },
            timeout=60
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            result = resp.json().get("response", "").strip()
            # ลบ markdown formatting
            result = re.sub(r'^\*+|\*+$', '', result)
            return result
            
    except Exception as e:
        if DEBUG:
            print(f"         ⚠️ Single block error: {e}")
    
    return text  # Fallback to original


def parse_numbered_response(response: str, expected_count: int) -> list:
    """แยก response ที่มีเลขลำดับ (1. 2. 3.) - ลบเลขลำดับ prompt ออกเสมอ"""
    lines = response.strip().split('\n')
    results = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # ลบเลขลำดับข้างหน้า (จาก prompt format) - ต้องลบเสมอ!
        cleaned = re.sub(r'^\d+[\.\)\-:]\s*', '', line)
        if cleaned:
            results.append(cleaned)
        else:
            # ถ้าลบแล้วไม่เหลืออะไร ใช้ line เดิม (แต่ strip เลขออก)
            results.append(line)
    
    # ถ้าได้ไม่ครบ ให้ลอง split แบบอื่น
    if len(results) < expected_count:
        # อาจจะไม่มีเลขลำดับ - ยังต้องลบเลขถ้ามี
        alt_results = []
        for line in lines:
            line = line.strip()
            if line:
                cleaned = re.sub(r'^\d+[\.\)\-:]\s*', '', line)
                alt_results.append(cleaned if cleaned else line)
        results = alt_results
    
    return results


def parse_marker_response(response: str, expected_count: int, original_texts: list = None) -> list:
    """แยก response ด้วย ###BLOCKX### markers - ไม่ validate, ให้ caller จัดการเอง"""
    results = [''] * expected_count
    
    # หา patterns ###BLOCK1###, ###BLOCK2###, etc.
    pattern = r'###BLOCK(\d+)###\s*(.+?)(?=###BLOCK\d+###|$)'
    matches = re.findall(pattern, response, re.DOTALL)
    
    for num_str, text in matches:
        idx = int(num_str) - 1
        if 0 <= idx < expected_count:
            cleaned = text.strip()
            # ลบ markdown formatting ที่ LLM อาจใส่มา
            cleaned = re.sub(r'^\*+|\*+$', '', cleaned)
            results[idx] = cleaned
    
    # ถ้าไม่พบ markers ให้ลอง split ด้วย newline
    if not any(results):
        lines = response.strip().split('\n')
        for i, line in enumerate(lines):
            if i < expected_count:
                # ลบ marker ถ้ามี
                cleaned = re.sub(r'^###BLOCK\d+###\s*', '', line.strip())
                # ลบเลขลำดับถ้ามี
                cleaned = re.sub(r'^\d+[\.\)\-:]\s*', '', cleaned)
                # ลบ markdown formatting
                cleaned = re.sub(r'^\*+|\*+$', '', cleaned)
                results[i] = cleaned if cleaned else ''
    
    # ไม่ fallback และไม่ validate ที่นี่ - ให้ translate_batch จัดการ
    return results


def validate_translation(original: str, translated: str, tgt_lang: str = None) -> tuple:
    """
    ตรวจสอบว่าผลลัพธ์การแปลถูกต้องหรือไม่
    Returns: (is_valid, reason)
    """
    if not translated:
        return False, "empty"
    
    # ตรวจสอบว่าเป็นส่วนของ prompt หรือไม่
    prompt_fragments = [
        "Preserve all numbers",
        "Keep the numbering",
        "Output ONLY",
        "no explanations",
        "###BLOCK",
        "Translate each line",
        "IMPORTANT:",
        "formatting from the original",
        # เพิ่ม patterns ที่ LLM อาจส่งผิด
        "No translation needed",
        "**Block",
        "(No translation",
        "Block 1:",
        "Block 2:",
        "Block 3:",
        "Block 4:",
        "Block 5:",
    ]
    
    for fragment in prompt_fragments:
        if fragment.lower() in translated.lower():
            return False, "contains prompt"
    
    # ตรวจสอบว่าแปลยาวเกินไปหรือไม่ (ยาวกว่า 4 เท่าของ original)
    # มักเกิดจาก LLM hallucination
    if len(original) > 10 and len(translated) > len(original) * 4:
        return False, "too long"
    
    # ตรวจสอบว่าแปลสั้นเกินไปหรือไม่ (ถ้า original ยาวกว่า 50 ตัวอักษร)
    if len(original) > 50 and len(translated) < len(original) * 0.3:
        return False, "too short"
    
    # ตรวจสอบว่ามีแค่ตัวเลขหรือไม่
    if re.match(r'^[\d\.\s\-\:]+$', translated):
        return False, "numbers only"
    
    # ตรวจสอบว่าผลลัพธ์ซ้ำกับต้นฉบับหรือไม่ (echo)
    # ลบ whitespace และ bullet points แล้วเทียบ
    orig_clean = re.sub(r'^[·•\-\*\d\.\)\s]+', '', original).strip()
    trans_clean = re.sub(r'^[·•\-\*\d\.\)\s]+', '', translated).strip()
    if orig_clean == trans_clean:
        return False, "same as original (echo)"
    
    # ตรวจสอบว่าอยู่ในภาษาเป้าหมายหรือไม่
    if tgt_lang:
        detected_lang = detect_language(translated)
        # ถ้าเป็นภาษาเดียวกับต้นฉบับ แสดงว่ายังไม่ได้แปล
        orig_lang = detect_language(original)
        if detected_lang == orig_lang and orig_lang != tgt_lang:
            return False, f"wrong language ({detected_lang})"
    
    return True, "ok"


def fix_number_prefix(original: str, translated: str, tgt_lang: str) -> str:
    """
    แก้ไขตัวเลขนำหน้าให้ถูกต้อง:
    1. ถ้า original ไม่มีเลข → ลบเลขที่ LLM เติมมา
    2. ถ้า original มีเลข → ตรวจสอบว่า translated มีเลขเดียวกัน
    """
    if not original or not translated:
        return translated
    
    # Pattern สำหรับเลขนำหน้า
    number_pattern = r'^(\d+)[\.\)\:\-\s]+'
    thai_prefix_pattern = r'^((?:บทที่|ข้อที่|ตอนที่|หัวข้อที่|ข้อ)\s*\d+)[\.\)\:\s]*'
    eng_prefix_pattern = r'^((?:Chapter|Section|Part|Item|No\.?)\s*\d+)[\.\)\:\s]*'
    
    # ตรวจสอบว่า original มีเลขนำหน้าไหม
    orig_number = None
    orig_prefix = None
    
    # ลอง pattern ต่างๆ
    match_num = re.match(number_pattern, original)
    match_thai = re.match(thai_prefix_pattern, original, re.IGNORECASE)
    match_eng = re.match(eng_prefix_pattern, original, re.IGNORECASE)
    
    if match_num:
        orig_number = match_num.group(1)
        orig_prefix = match_num.group(0)
    elif match_thai:
        orig_prefix = match_thai.group(1)
        num_in_prefix = re.search(r'\d+', orig_prefix)
        orig_number = num_in_prefix.group() if num_in_prefix else None
    elif match_eng:
        orig_prefix = match_eng.group(1)
        num_in_prefix = re.search(r'\d+', orig_prefix)
        orig_number = num_in_prefix.group() if num_in_prefix else None
    
    # ตรวจสอบว่า translated มีเลขนำหน้าไหม
    trans_match = re.match(number_pattern, translated)
    
    if orig_number is None:
        # Original ไม่มีเลข → ลบเลขที่ LLM เติมมา
        if trans_match:
            translated = re.sub(number_pattern, '', translated)
    else:
        # Original มีเลข → ตรวจสอบว่า translated มีเลขเดียวกัน
        if not trans_match:
            # Translated ไม่มีเลข → เพิ่มเลขกลับ
            if tgt_lang == "eng_Latn":
                if match_thai:
                    # แปลง prefix ไทยเป็นอังกฤษ
                    if "บทที่" in orig_prefix:
                        translated = f"Chapter {orig_number}: {translated}"
                    elif "ข้อที่" in orig_prefix or "ข้อ" in orig_prefix:
                        translated = f"Item {orig_number}. {translated}"
                    else:
                        translated = f"{orig_number}. {translated}"
                else:
                    translated = f"{orig_number}. {translated}"
            else:
                # ไทย
                if match_eng:
                    if "chapter" in orig_prefix.lower():
                        translated = f"บทที่ {orig_number} {translated}"
                    else:
                        translated = f"{orig_number}. {translated}"
                else:
                    translated = f"{orig_number}. {translated}"
        else:
            # Translated มีเลข → ตรวจว่าเลขตรงกันไหม
            trans_number = trans_match.group(1)
            if trans_number != orig_number:
                # เลขไม่ตรง → แก้ไข
                translated = re.sub(number_pattern, f"{orig_number}. ", translated)
    
    return translated


def extract_number_prefix(text: str) -> tuple:
    """
    ดึง prefix ที่เป็นตัวเลขออกจากต้นฉบับ
    เช่น "8 กลยุทธ์..." → ("8 ", "กลยุทธ์...")
         "บทที่ 3 วิธีการ..." → ("บทที่ 3 ", "วิธีการ...")
    Returns: (prefix, remaining_text)
    """
    if not text:
        return "", text
    
    # Pattern 1: ตัวเลขนำหน้า (เช่น "8 กลยุทธ์...")
    match1 = re.match(r'^(\d+[\.\)\:\s]+)', text)
    if match1:
        return match1.group(1), text[len(match1.group(1)):]
    
    # Pattern 2: บทที่ X, ข้อ X, ตอนที่ X ฯลฯ
    match2 = re.match(r'^((?:บทที่|ข้อที่|ตอนที่|หัวข้อที่|ลำดับที่|หมวดที่)\s*\d+[\.\)\:\s]*)', text, re.IGNORECASE)
    if match2:
        return match2.group(1), text[len(match2.group(1)):]
    
    # Pattern 3: Chapter X, Section X, etc.
    match3 = re.match(r'^((?:Chapter|Section|Part|Item|No\.?|Number)\s*\d+[\.\)\:\s]*)', text, re.IGNORECASE)
    if match3:
        return match3.group(1), text[len(match3.group(1)):]
    
    return "", text


def restore_number_prefix(original_prefix: str, translated: str, tgt_lang: str) -> str:
    """
    ใส่ prefix กลับเข้าไปในข้อความที่แปลแล้ว
    แปลง prefix ให้ตรงกับภาษาเป้าหมาย
    """
    if not original_prefix:
        return translated
    
    # ดึงตัวเลขจาก prefix
    number_match = re.search(r'\d+', original_prefix)
    if not number_match:
        return original_prefix + translated
    
    number = number_match.group()
    
    # แปลง prefix ตามภาษาเป้าหมาย
    if tgt_lang == "eng_Latn":
        # Thai → English
        if "บทที่" in original_prefix:
            return f"Chapter {number}: {translated}"
        elif "ข้อที่" in original_prefix or "ข้อ" in original_prefix:
            return f"Item {number}: {translated}"
        elif "ตอนที่" in original_prefix:
            return f"Part {number}: {translated}"
        elif "หัวข้อที่" in original_prefix:
            return f"Section {number}: {translated}"
        else:
            # ตัวเลขเดี่ยวๆ
            return f"{number}. {translated}"
    else:
        # English → Thai
        if "chapter" in original_prefix.lower():
            return f"บทที่ {number} {translated}"
        elif "section" in original_prefix.lower():
            return f"หัวข้อที่ {number} {translated}"
        elif "part" in original_prefix.lower():
            return f"ตอนที่ {number} {translated}"
        else:
            return f"{number}. {translated}"


def wrap_text(text: str, font, max_width: int, draw) -> list:
    """ตัดคำให้พอดี width"""
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        width = bbox[2] - bbox[0]
        
        if width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    return lines if lines else [text]


def fit_text_to_bbox(draw, text: str, bbox_width: int, bbox_height: int, 
                     max_font: int = 24, min_font: int = 8):
    """คำนวณ font size และ wrap text ให้พอดี bbox - เลือก font ตามภาษาของ text"""
    # ตรวจจับภาษาของ text เพื่อเลือก font ที่เหมาะสม
    detected_lang = detect_language(text)
    
    for size in range(max_font, min_font - 1, -1):
        font = get_font(size, detected_lang)
        wrapped = wrap_text(text, font, bbox_width, draw)
        
        # คำนวณความสูงรวม
        total_height = 0
        for line in wrapped:
            line_bbox = draw.textbbox((0, 0), line, font=font)
            total_height += (line_bbox[3] - line_bbox[1]) + 2
        
        if total_height <= bbox_height:
            return font, wrapped
    
    # ถ้าใหญ่สุดก็ยังไม่พอ ใช้ min font
    font = get_font(min_font, detected_lang)
    wrapped = wrap_text(text, font, bbox_width, draw)
    return font, wrapped


def extract_text_blocks(doc, page_no: int) -> list:
    """ดึง text blocks จาก DoclingDocument สำหรับหน้าที่กำหนด (ข้ามข้อความในรูปภาพ)"""
    blocks = []
    
    # หา text refs ที่อยู่ในรูปภาพ (ไม่ต้องแปล)
    picture_text_refs = set()
    for pic in doc.pictures:
        for child in pic.children:
            if hasattr(child, '$ref'):
                picture_text_refs.add(child['$ref'])
            elif hasattr(child, 'self_ref'):
                picture_text_refs.add(child.self_ref)
    
    # Track list item numbering
    list_item_counter = 0
    
    for item in doc.texts:
        # ข้าม furniture (header/footer)
        if item.label in [DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER]:
            continue
        
        # ข้าม text ที่อยู่ในรูปภาพ
        if hasattr(item, 'self_ref') and item.self_ref in picture_text_refs:
            if DEBUG:
                print(f"      ⏭️ SKIP (in picture): {item.text[:30]}...")
            continue
        
        # ตรวจสอบว่า parent เป็น picture หรือเปล่า
        if hasattr(item, 'parent') and item.parent:
            parent_ref = item.parent.get('$ref', '') if isinstance(item.parent, dict) else getattr(item.parent, '$ref', '')
            if 'pictures' in str(parent_ref):
                if DEBUG:
                    print(f"      ⏭️ SKIP (parent is picture): {item.text[:30]}...")
                continue
            
        if item.prov:
            for prov in item.prov:
                if prov.page_no == page_no:
                    text = item.text
                    
                    # ถ้าเป็น list_item ให้เพิ่ม marker
                    if str(item.label) == "DocItemLabel.LIST_ITEM" or "list_item" in str(item.label).lower():
                        # ตรวจสอบว่ามี marker หรือไม่
                        marker = getattr(item, 'marker', None)
                        if marker:
                            text = f"{marker} {item.text}"
                        else:
                            # ถ้าไม่มี marker ให้ใช้ตัวเลข
                            list_item_counter += 1
                            text = f"{list_item_counter}. {item.text}"
                    
                    blocks.append({
                        'text': text,
                        'original_text': item.text,
                        'bbox': prov.bbox,
                        'page': prov.page_no,
                        'label': str(item.label) if item.label else "text",
                        'marker': getattr(item, 'marker', None)
                    })
    
    return blocks


def extract_all_texts(doc) -> list:
    """
    ดึงทุก texts จาก DoclingDocument สำหรับ documents ที่ไม่มี pages (DOCX/PPTX/XLSX/HTML)
    Returns: list of blocks with text and label
    """
    blocks = []
    
    for item in doc.texts:
        text = item.text if hasattr(item, 'text') else str(item)
        if not text or not text.strip():
            continue
        
        label = str(item.label) if hasattr(item, 'label') else "text"
        
        # ถ้าเป็น list_item ให้เพิ่ม marker
        if "list_item" in label.lower():
            marker = getattr(item, 'marker', None)
            if marker:
                text = f"{marker} {text}"
        
        blocks.append({
            'text': text,
            'label': label,
            # ไม่มี bbox สำหรับ text-only documents
            'bbox': None
        })
    
    return blocks


def extract_tables(doc, page_no: int) -> list:
    """ดึงตารางจาก DoclingDocument สำหรับหน้าที่กำหนด"""
    tables = []
    
    for table in doc.tables:
        if table.prov:
            for prov in table.prov:
                if prov.page_no == page_no:
                    # ดึงข้อมูล cells
                    cells = []
                    if hasattr(table, 'data') and table.data:
                        # Docling table structure
                        for row_idx, row in enumerate(table.data.grid):
                            for col_idx, cell in enumerate(row):
                                cells.append({
                                    'text': cell.text if hasattr(cell, 'text') else str(cell),
                                    'row': row_idx,
                                    'col': col_idx
                                })
                    
                    tables.append({
                        'bbox': prov.bbox,
                        'page': prov.page_no,
                        'num_rows': table.data.num_rows if hasattr(table, 'data') and table.data else 0,
                        'num_cols': table.data.num_cols if hasattr(table, 'data') and table.data else 0,
                        'cells': cells
                    })
    
    return tables


def draw_table(draw, table_data, page_height, scale, font, tgt_lang, log_file=None):
    """วาดตารางพร้อมข้อความแปล"""
    bbox = table_data['bbox']
    
    # แปลง bbox เป็น top-left origin
    bbox_tl = bbox.to_top_left_origin(page_height=page_height)
    
    x1 = int(bbox_tl.l * scale)
    y1 = int(bbox_tl.t * scale)
    x2 = int(bbox_tl.r * scale)
    y2 = int(bbox_tl.b * scale)
    
    table_width = x2 - x1
    table_height = y2 - y1
    
    num_rows = table_data['num_rows']
    num_cols = table_data['num_cols']
    cells = table_data['cells']
    
    if num_rows == 0 or num_cols == 0:
        return
    
    cell_width = table_width // num_cols
    cell_height = table_height // num_rows
    
    # วาดเส้นขอบตาราง
    line_color = (0, 0, 0)  # black
    
    # วาดเส้นแนวนอน
    for i in range(num_rows + 1):
        y = y1 + (i * cell_height)
        draw.line([(x1, y), (x2, y)], fill=line_color, width=1)
    
    # วาดเส้นแนวตั้ง
    for j in range(num_cols + 1):
        x = x1 + (j * cell_width)
        draw.line([(x, y1), (x, y2)], fill=line_color, width=1)
    
    # ใส่ข้อความในแต่ละ cell
    padding = 4
    
    # รวบรวม cells ที่มีข้อความ
    cells_to_translate = []
    for cell in cells:
        text = cell.get('text', '')
        if text and len(text.strip()) >= 1:
            text = normalize_ocr_text(text)
            cells_to_translate.append({
                'row': cell['row'],
                'col': cell['col'],
                'text': text
            })
    
    if not cells_to_translate:
        return
    
    # แปลทั้งตารางใน 1 API call
    translated_cells = translate_table_cells(cells_to_translate, tgt_lang)
    
    # Log table translation
    if DEBUG and log_file:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"TABLE: {num_rows}x{num_cols} cells at [{x1}, {y1}] - [{x2}, {y2}]\n")
            f.write(f"{'='*60}\n\n")
            for cell in translated_cells:
                row = cell['row']
                col = cell['col']
                original = cell.get('text', '')
                translated = cell.get('translated', original)
                was_translated = cell.get('was_translated', False)
                detected_lang = cell.get('detected_lang', 'unknown')
                status = "TRANSLATED" if was_translated else "SKIPPED"
                f.write(f"Cell [{row},{col}] [{status}] (detected: {detected_lang})\n")
                f.write(f"  Original: {original}\n")
                f.write(f"  Result: {translated}\n\n")
    
    # วาดแต่ละ cell
    for cell in translated_cells:
        row = cell['row']
        col = cell['col']
        translated = cell.get('translated', cell.get('text', ''))
        
        # คำนวณตำแหน่งและขนาด cell
        cx = x1 + (col * cell_width) + padding
        cy = y1 + (row * cell_height) + padding
        available_width = cell_width - (padding * 2)
        available_height = cell_height - (padding * 2)
        
        if available_width < 10 or available_height < 10:
            continue
        
        # หา font size ที่พอดี - เริ่มจากใหญ่สุด
        font_size = 18  # เพิ่มจาก 12 เป็น 18
        min_font_size = 10  # เพิ่มจาก 6 เป็น 10
        
        while font_size >= min_font_size:
            small_font = get_font(font_size)
            wrapped_lines = wrap_text(translated, small_font, available_width, draw)
            
            # คำนวณความสูงรวม
            total_height = 0
            for line in wrapped_lines:
                line_bbox = draw.textbbox((0, 0), line, font=small_font)
                total_height += (line_bbox[3] - line_bbox[1]) + 2
            
            if total_height <= available_height:
                break  # พอดี!
            
            font_size -= 1
        
        # วาดข้อความ
        current_y = cy
        for line in wrapped_lines:
            line_bbox = draw.textbbox((0, 0), line, font=small_font)
            line_height = line_bbox[3] - line_bbox[1]
            
            if current_y + line_height <= cy + available_height:
                draw.text((cx, current_y), line, fill="black", font=small_font)
                current_y += line_height + 2


def translate_table_cells(cells: list, tgt_lang: str) -> list:
    """
    แปลทุก cell ในตารางใน 1 API call
    """
    global total_translation_time, translation_stats
    
    if not cells:
        return cells
    
    # แยก cells ที่ต้องแปล vs ไม่ต้องแปล
    to_translate = []
    already_target = []
    
    for i, cell in enumerate(cells):
        text = cell['text']
        need_translate, detected_lang = should_translate(text, tgt_lang)
        
        if need_translate:
            to_translate.append((i, cell, detected_lang))
        else:
            already_target.append((i, cell, detected_lang))
            translation_stats["skipped"] += 1
    
    # เตรียม results
    results = [None] * len(cells)
    
    # ใส่ cells ที่ไม่ต้องแปล
    for i, cell, detected_lang in already_target:
        results[i] = {
            **cell,
            'translated': cell['text'],
            'detected_lang': detected_lang,
            'was_translated': False
        }
    
    if not to_translate:
        return results
    
    if DEBUG:
        print(f"      📊 Table cells: ต้องแปล {len(to_translate)}, ข้าม {len(already_target)}")
    
    # สร้าง prompt รวม
    lines_text = []
    for idx, (i, cell, detected_lang) in enumerate(to_translate):
        lines_text.append(f"{idx + 1}. {cell['text']}")
    
    combined_text = "\n".join(lines_text)
    
    if tgt_lang == "eng_Latn":
        prompt = f"""Translate each line to English. Keep the numbering format (1. 2. 3.).
IMPORTANT: Preserve all original numbers from the source text.
Output ONLY the translations, no explanations.

{combined_text}"""
    else:
        prompt = f"""Translate each line to Thai. Keep the numbering format (1. 2. 3.).
IMPORTANT: Preserve all original numbers from the source text.
Output ONLY the translations, no explanations.

{combined_text}"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": QWEN_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2048}
            },
            timeout=180
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            response = resp.json().get("response", "").strip()
            
            # Parse response
            translated_lines = parse_numbered_response(response, len(to_translate))
            
            # Map กลับไป cells
            for idx, (i, cell, detected_lang) in enumerate(to_translate):
                if idx < len(translated_lines):
                    translated = translated_lines[idx]
                    translation_stats["translated"] += 1
                else:
                    translated = cell['text']  # fallback
                
                results[i] = {
                    **cell,
                    'translated': translated,
                    'detected_lang': detected_lang,
                    'was_translated': True
                }
            
            return results
            
    except Exception as e:
        print(f"   ⚠️ Table translation error: {e}")
    
    # Fallback: ใส่ต้นฉบับ
    for i, cell, detected_lang in to_translate:
        results[i] = {
            **cell,
            'translated': cell['text'],
            'detected_lang': detected_lang,
            'was_translated': False
        }
    
    return results




def process_pdf_with_docling(pdf_path: str, tgt_lang: str):
    """Process PDF ด้วย Docling"""
    global total_translation_time, CURRENT_FONT_PATH
    total_translation_time = 0
    
    # Set font สำหรับ target language
    CURRENT_FONT_PATH = FONT_PATHS.get(tgt_lang, FONT_PATHS["default"])
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    
    start = time.time()
    
    print(f"\n📄 PDF: {pdf_path}")
    print("📥 โหลด Docling DocumentConverter...")
    
    converter = DocumentConverter()
    
    print("🔍 แปลง PDF (อาจใช้เวลาครั้งแรก)...")
    conversion_start = time.time()
    result = converter.convert(pdf_path)
    doc = result.document
    conversion_time = time.time() - conversion_start
    print(f"✅ แปลงเสร็จใน {conversion_time:.1f}s")
    
    # Debug: บันทึก raw document
    if DEBUG:
        import json
        json_path = os.path.join(LOG_DIR, "docling_output.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(doc.export_to_dict(), ensure_ascii=False, indent=2))
        print(f"   📝 Saved: {json_path}")
    
    # ดึงจำนวนหน้า
    num_pages = len(doc.pages)
    print(f"   📄 {num_pages} หน้า")
    
    images = []
    total_blocks = 0
    translated_pages = {}  # เก็บผลแปลสำหรับ export
    docling_result = {"pages": {}}  # สำหรับ export service
    
    # ★ Check if document has pages (PDF) or is text-only (DOCX/PPTX/XLSX/HTML)
    if num_pages == 0:
        print(f"\n📄 Document ไม่มี pages (text-only document)")
        
        # ดึง texts ทั้งหมด
        blocks = extract_all_texts(doc)
        print(f"   📦 {len(blocks)} text blocks")
        total_blocks = len(blocks)
        
        if blocks:
            # แปลทุก block (ใช้ batch translation)
            print(f"   🤖 แปล...")
            
            # Translate blocks
            translated_blocks = []
            for block in blocks:
                text = normalize_ocr_text(block['text'])
                need_translate, detected_lang = should_translate(text, tgt_lang)
                
                if need_translate:
                    # ใช้ Qwen แปล
                    translated = translate_single_qwen(text, tgt_lang)
                    is_valid, reason = validate_translation(text, translated, tgt_lang)
                    if not is_valid:
                        # Fallback to NLLB
                        src_lang = detected_lang if detected_lang != "unknown" else "tha_Thai"
                        translated = translate_with_nllb(text, src_lang, tgt_lang)
                    translation_stats["translated"] += 1
                else:
                    translated = text
                    translation_stats["skipped"] += 1
                
                translated_blocks.append({
                    **block,
                    'text': translated,
                    'original_text': block['text'],
                    'detected_lang': detected_lang,
                    'was_translated': need_translate
                })
            
            # Store for export - virtual page 1
            translated_pages[1] = translated_blocks
            docling_result["pages"][1] = {
                "width": 595,  # A4 width in points
                "height": 842,  # A4 height in points
                "blocks": translated_blocks
            }
            num_pages = 1  # Set to 1 for export
            
            print(f"   ✅ แปลเสร็จ {len(translated_blocks)} blocks")
    else:
        # ★ PDF mode - has pages with layout
        for page_no in range(1, num_pages + 1):
            print(f"\n{'='*50}")
            print(f"📖 หน้า {page_no}/{num_pages}")
            
            # ดึง text blocks
            blocks = extract_text_blocks(doc, page_no)
            print(f"   📦 {len(blocks)} text blocks")
            total_blocks += len(blocks)
            
            # ดึงตาราง
            tables = extract_tables(doc, page_no)
            if tables:
                print(f"   📊 {len(tables)} tables detected")
            
            if not blocks and not tables:
                continue
            
            # ดึงขนาดหน้า - pages อาจเป็น dict หรือ object
            if isinstance(doc.pages, dict):
                page = doc.pages.get(str(page_no)) or doc.pages.get(page_no)
            else:
                page = doc.pages[page_no]
            
            # Store page info for export
            docling_result["pages"][page_no] = {
                "width": page.size.width,
                "height": page.size.height,
                "blocks": []
            }
            
            # Debug: print page size
            if DEBUG:
                print(f"   📏 Page size: {page.size.width} x {page.size.height} (original PDF points)")
            
            page_width = int(page.size.width * (DPI / 72))
            page_height = int(page.size.height * (DPI / 72))
            
            if DEBUG:
                print(f"   📏 Canvas size: {page_width} x {page_height} (pixels at {DPI} DPI)")
            
            # สร้าง white canvas
            canvas = Image.new('RGB', (page_width, page_height), 'white')

            draw = ImageDraw.Draw(canvas)
            
            # Debug log
            if DEBUG:
                log_file = os.path.join(LOG_DIR, f"page_{page_no:03d}_blocks.txt")
                with open(log_file, 'w', encoding='utf-8') as f:
                    f.write(f"Page {page_no} - Text Blocks\n")
                    f.write("=" * 60 + "\n\n")
            else:
                log_file = None
            
            print("   🤖 แปล (full-page)...")
            
            # แปลทั้งหน้าใน 1 API call
            translated_blocks = translate_page_blocks(blocks, tgt_lang)
            
            # เก็บ translated blocks สำหรับ export
            translated_pages[page_no] = translated_blocks
            docling_result["pages"][page_no]["blocks"] = translated_blocks
            
            # วาดแต่ละ block
            scale = DPI / 72
            for i, block in enumerate(translated_blocks):
                if block is None:
                    continue
                
                bbox = block['bbox']
                translated = block.get('translated', block.get('text', ''))
                detected_lang = block.get('detected_lang', 'unknown')
                was_translated = block.get('was_translated', False)
                
                # แปลง bbox จาก bottom-left origin เป็น top-left
                bbox_tl = bbox.to_top_left_origin(page_height=page.size.height)
                
                x1 = int(bbox_tl.l * scale)
                y1 = int(bbox_tl.t * scale)
                x2 = int(bbox_tl.r * scale)
                y2 = int(bbox_tl.b * scale)
                
                box_width = x2 - x1
                box_height = y2 - y1
                
                # Debug log
                if DEBUG and log_file:
                    status = "TRANSLATED" if was_translated else "SKIPPED"
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"Block {i+1} [{status}] (detected: {detected_lang}): [{x1}, {y1}] - [{x2}, {y2}]\n")
                        f.write(f"  Label: {block['label']}\n")
                        f.write(f"  Original: {block.get('text', '')}\n")
                        f.write(f"  Result: {translated}\n\n")
                
                # Fit text และวาด
                if box_width > 10 and box_height > 10:
                    font, wrapped_lines = fit_text_to_bbox(
                        draw, translated, box_width, box_height
                    )
                    
                    # วาดแต่ละบรรทัด
                    current_y = y1
                    for line in wrapped_lines:
                        line_bbox = draw.textbbox((0, 0), line, font=font)
                        line_height = line_bbox[3] - line_bbox[1]
                        
                        if current_y + line_height <= y2:
                            draw.text((x1, current_y), line, font=font, fill="black")
                            current_y += line_height + 2
            
            # วาดตาราง
            scale = DPI / 72
            for table_data in tables:
                print(f"   📊 วาดตาราง {table_data['num_rows']}x{table_data['num_cols']}...")
                draw_table(draw, table_data, page.size.height, scale, get_font(12), tgt_lang, log_file)
            
            # บันทึก
            out_path = os.path.join(OUTPUT_DIR, f"translated_{page_no:03d}.png")
            canvas.save(out_path)
            images.append(out_path)
            print(f"   ✅ Saved: {out_path}")
    
    # สร้าง PDF
    print(f"\n{'='*50}")
    print("📦 สร้าง PDF...")
    
    if images:
        # ใช้ PyMuPDF กับ pixmap เพื่อหลีกเลี่ยงปัญหา rotation
        import fitz
        
        pdf_doc = fitz.open()
        
        for img_path in images:
            # อ่านภาพเป็น pixmap
            pix = fitz.Pixmap(img_path)
            
            # คำนวณขนาดหน้า PDF (pixels → points)
            page_width = pix.width * 72 / DPI
            page_height = pix.height * 72 / DPI
            
            # สร้างหน้าใหม่ด้วยขนาดที่ถูกต้อง
            page = pdf_doc.new_page(width=page_width, height=page_height)
            
            # แทรก pixmap โดยตรง
            rect = fitz.Rect(0, 0, page_width, page_height)
            page.insert_image(rect, pixmap=pix)
            
            pix = None  # release memory
        
        pdf_out = os.path.join(OUTPUT_DIR, "translated_docling.pdf")
        pdf_doc.save(pdf_out)
        pdf_doc.close()
        
        print(f"   📄 {pdf_out}")
    else:
        print("   ⏭️ ไม่มี images - ข้าม PDF (document ไม่มี layout)")
    
    # ★ Export เป็นรูปแบบอื่นๆ (ทำได้ทั้ง PDF และ text-only documents)
    if translated_pages:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from app.services.export_service import export_service
            
            # สร้าง doc_result สำหรับ export_service
            doc_result_export = {
                "num_pages": len(translated_pages),
                "pages": {}
            }
            for page_no in translated_pages.keys():
                doc_result_export["pages"][page_no] = {
                    "width": docling_result["pages"][page_no]["width"],
                    "height": docling_result["pages"][page_no]["height"],
                    "blocks": translated_pages[page_no]
                }
            
            # Export
            docx_path = os.path.join(OUTPUT_DIR, "translated.docx")
            pptx_path = os.path.join(OUTPUT_DIR, "translated.pptx")
            xlsx_path = os.path.join(OUTPUT_DIR, "translated.xlsx")
            html_path = os.path.join(OUTPUT_DIR, "translated.html")
            
            export_service.export_to_docx(doc_result_export, docx_path)
            export_service.export_to_pptx(doc_result_export, pptx_path)
            export_service.export_to_xlsx(doc_result_export, xlsx_path)
            export_service.export_to_html(doc_result_export, html_path)
            
            print(f"   📝 {docx_path}")
            print(f"   📊 {pptx_path}")
            print(f"   📈 {xlsx_path}")
            print(f"   🌐 {html_path}")
        except Exception as e:
            print(f"   ⚠️ Export error: {e}")
    
    elapsed = time.time() - start
    
    print(f"\n🎉 เสร็จ!")
    print(f"   ⏱️ Docling: {conversion_time:.1f}s")
    print(f"   ⏱️ แปล: {total_translation_time:.1f}s")
    print(f"   ⏱️ รวม: {elapsed:.1f}s ({elapsed/60:.1f} นาที)")
    print(f"   📊 {total_blocks} blocks, {num_pages} หน้า")
    print(f"   ✅ Translated: {translation_stats['translated']} blocks")
    print(f"   ⏭️ Skipped: {translation_stats['skipped']} blocks (เป็นภาษาเป้าหมายแล้ว)")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("📄 PDF Translation with Docling (v1.0)")
    print("=" * 60)
    print(f"   โมเดลแปล: {QWEN_MODEL}")
    print("   OCR: Docling (IBM Research)")
    print("   Features:")
    print("   ✅ Block-based extraction")
    print("   ✅ Layout-aware understanding")
    print("   ✅ Auto text wrapping")
    print("   ✅ White canvas output")
    print("=" * 60)
    
    if not os.path.exists(PDF_PATH):
        print(f"❌ ไม่พบ: {PDF_PATH}")
        exit(1)
    
    # ตรวจสอบ Ollama
    print("\n📥 ตรวจสอบ Ollama...")
    try:
        resp = requests.post(OLLAMA_URL, json={"model": QWEN_MODEL, "prompt": "Hi", "stream": False}, timeout=60)
        if resp.status_code == 200:
            print(f"✅ Qwen2.5 พร้อม ({QWEN_MODEL})")
    except Exception as e:
        print(f"❌ Ollama error: {e}")
        exit(1)
    
    # ===== รหัสภาษา NLLB (เปลี่ยนตรงนี้) =====
    # ภาษาเป้าหมายที่รองรับ:
    #   eng_Latn  = English (อังกฤษ)
    #   tha_Thai  = Thai (ไทย)
    #   zho_Hans  = Chinese Simplified (จีนตัวย่อ)
    #   jpn_Jpan  = Japanese (ญี่ปุ่น)
    #   kor_Hang  = Korean (เกาหลี)
    # ==========================================
    process_pdf_with_docling(PDF_PATH, "eng_Latn")
