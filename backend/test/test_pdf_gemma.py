"""
PDF Translation: Docling-based OCR with Gemma3
- ใช้ Docling สำหรับ OCR ที่แม่นยำ
- ใช้ Gemma3 แปลภาษา (Google)
"""
import os
import sys
import time
import requests
import re
import unicodedata

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from PIL import Image, ImageDraw, ImageFont
from docling.document_converter import DocumentConverter
from docling_core.types.doc import DocItemLabel

# ===== ตั้งค่า =====
PDF_PATH = "./test.pdf"
OUTPUT_DIR = "./output_images/pdf_gemma2"
DPI = 150

# Ollama settings (Gemma3)
OLLAMA_URL = "http://localhost:11434/api/generate"
GEMMA_MODEL = "gemma3"

# Font - เลือกตามภาษา
FONT_PATHS = {
    "tha_Thai": "C:/Windows/Fonts/tahoma.ttf",      # Thai
    "zho_Hans": "C:/Windows/Fonts/msyh.ttc",        # Chinese Simplified
    "zho_Hant": "C:/Windows/Fonts/msyh.ttc",        # Chinese Traditional
    "jpn_Jpan": "C:/Windows/Fonts/msgothic.ttc",    # Japanese
    "kor_Hang": "C:/Windows/Fonts/malgun.ttf",      # Korean
    "default": "C:/Windows/Fonts/arial.ttf",        # Default
}
CURRENT_FONT_PATH = FONT_PATHS["default"]

# Debug
DEBUG = True
LOG_DIR = "./output_images/pdf_gemma2/logs"

# Timing
total_translation_time = 0


def get_font(size=16, tgt_lang=None):
    global CURRENT_FONT_PATH
    
    if tgt_lang:
        font_path = FONT_PATHS.get(tgt_lang, FONT_PATHS["default"])
    else:
        font_path = CURRENT_FONT_PATH
    
    if os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except:
            pass
    
    for path in FONT_PATHS.values():
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                continue
    
    return ImageFont.load_default()


def normalize_ocr_text(text: str) -> str:
    """Normalize ข้อความหลัง OCR"""
    if not text:
        return text
    
    text = unicodedata.normalize('NFC', text)
    
    # Quotes & Apostrophes
    quote_replacements = {
        '"': '"', '"': '"', '„': '"', '‟': '"',
        '«': '"', '»': '"', '‹': "'", '›': "'",
        ''': "'", ''': "'", '‛': "'", '`': "'",
        '′': "'", '″': '"',
    }
    
    # Dashes & Hyphens
    dash_replacements = {
        '—': '-', '–': '-', '‒': '-', '―': '-',
        '⁃': '-', '‐': '-', '‑': '-', '−': '-',
    }
    
    # Spaces
    space_replacements = {
        '\xa0': ' ', '\u2000': ' ', '\u2001': ' ', '\u2002': ' ',
        '\u2003': ' ', '\u2004': ' ', '\u2005': ' ', '\u2006': ' ',
        '\u2007': ' ', '\u2008': ' ', '\u2009': ' ', '\u200a': ' ',
        '\u200b': '', '\u200c': '', '\u200d': '', '\u202f': ' ',
        '\u205f': ' ', '\u3000': ' ', '\ufeff': '',
    }
    
    # Dots & Ellipsis
    dot_replacements = {
        '…': '...', '⋯': '...', '‥': '..', '․': '.',
        '·': '.', '•': '-', '◦': '-', '‣': '-', '⁃': '-',
    }
    
    # Ligatures
    ligature_replacements = {
        'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff', 'ﬃ': 'ffi', 'ﬄ': 'ffl',
        'ﬅ': 'st', 'ﬆ': 'st', 'Ĳ': 'IJ', 'ĳ': 'ij',
        'Œ': 'OE', 'œ': 'oe', 'Æ': 'AE', 'æ': 'ae',
    }
    
    # Fractions
    fraction_replacements = {
        '½': '1/2', '⅓': '1/3', '⅔': '2/3', '¼': '1/4', '¾': '3/4',
        '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
        '⅙': '1/6', '⅚': '5/6', '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
    }
    
    # Symbols
    symbol_replacements = {
        '™': '(TM)', '®': '(R)', '©': '(C)', '℗': '(P)',
        '№': 'No.', '℃': 'C', '℉': 'F', '°': ' degrees ',
        '±': '+/-', '×': 'x', '÷': '/', '≈': '~', '≠': '!=',
        '≤': '<=', '≥': '>=', '←': '<-', '→': '->', '↔': '<->',
        '⇐': '<=', '⇒': '=>',
    }
    
    # Currency
    currency_replacements = {
        '฿': 'THB ', '€': 'EUR ', '£': 'GBP ', '¥': 'JPY ',
        '₩': 'KRW ', '₹': 'INR ', '₽': 'RUB ',
    }
    
    # Superscripts & Subscripts
    script_replacements = {
        '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4',
        '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9',
        '₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4',
        '₅': '5', '₆': '6', '₇': '7', '₈': '8', '₉': '9',
    }
    
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
    
    text = ''.join(c for c in text if c in '\n\t' or not unicodedata.category(c).startswith('C'))
    text = re.sub(r' +', ' ', text)
    
    return text.strip()


def detect_language(text: str) -> str:
    """ตรวจจับภาษาหลักของข้อความ"""
    if not text:
        return "unknown"
    
    thai = sum(1 for c in text if '\u0e00' <= c <= '\u0e7f')
    japanese = sum(1 for c in text if '\u3040' <= c <= '\u30ff')
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    korean = sum(1 for c in text if '\uac00' <= c <= '\ud7af')
    
    total = len(text.replace(" ", ""))
    if total == 0:
        return "unknown"
    
    lang_ratios = {
        "tha_Thai": thai / total,
        "jpn_Jpan": japanese / total,
        "zho_Hans": chinese / total,
        "kor_Hang": korean / total
    }
    
    max_lang = max(lang_ratios, key=lang_ratios.get)
    if lang_ratios[max_lang] > 0.2:
        return max_lang
    
    return "eng_Latn"


def should_translate(text: str, target_lang: str):
    """ตรวจว่า block นี้ต้องแปลไหม"""
    detected = detect_language(text)
    if detected == target_lang:
        return False, detected
    return True, detected


def translate_single_gemma(text: str, tgt_lang: str) -> str:
    """แปลข้อความเดียวด้วย Gemma3"""
    global total_translation_time
    
    if not text or len(text.strip()) < 2:
        return text
    
    # Map language codes to names
    lang_names = {
        "eng_Latn": "English",
        "tha_Thai": "Thai",
        "zho_Hans": "Chinese (Simplified)",
        "zho_Hant": "Chinese (Traditional)",
        "jpn_Jpan": "Japanese",
        "kor_Hang": "Korean",
    }
    target_name = lang_names.get(tgt_lang, tgt_lang)
    
    prompt = f"""Translate the following text to {target_name}. 
Preserve all numbers and formatting.
Output ONLY the translation, no explanations.

{text}"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": GEMMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512}
            },
            timeout=120
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            result = resp.json().get("response", "").strip()
            result = re.sub(r'^\*+|\*+$', '', result)
            return result
            
    except Exception as e:
        if DEBUG:
            print(f"         ⚠️ Gemma3 error: {e}")
    
    return ""


def translate_batch_gemma(batch: list, tgt_lang: str) -> list:
    """แปล batch ด้วย Gemma3"""
    global total_translation_time
    
    if not batch:
        return []
    
    original_texts = [text for (i, block, text, detected_lang) in batch]
    results = [''] * len(batch)
    src_lang = batch[0][3] if batch[0][3] != "unknown" else "tha_Thai"
    
    # สร้าง prompt
    lines_text = []
    for idx, (i, block, text, detected_lang) in enumerate(batch):
        lines_text.append(f"###BLOCK{idx + 1}### {text}")
    
    combined_text = "\n".join(lines_text)
    
    lang_names = {
        "eng_Latn": "English",
        "tha_Thai": "Thai",
        "zho_Hans": "Chinese (Simplified)",
        "zho_Hant": "Chinese (Traditional)",
        "jpn_Jpan": "Japanese",
        "kor_Hang": "Korean",
    }
    target_name = lang_names.get(tgt_lang, tgt_lang)
    
    prompt = f"""Translate each line to {target_name} ONLY. Keep the ###BLOCKX### markers exactly as they are.
CRITICAL: Output ONLY {target_name} language.
IMPORTANT: Preserve all numbers and formatting from the original text.
Output ONLY the translations with their markers, no explanations.

{combined_text}"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": GEMMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2048}
            },
            timeout=120
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            response = resp.json().get("response", "").strip()
            translated_lines = parse_marker_response(response, len(batch), original_texts)
            
            failed_indices = []
            for idx, translated in enumerate(translated_lines):
                is_valid, reason = validate_translation(original_texts[idx], translated, tgt_lang)
                if is_valid:
                    results[idx] = translated
                else:
                    failed_indices.append(idx)
                    if DEBUG:
                        print(f"         ⚠️ Block {idx+1} invalid ({reason}), will retry")
            
            # Retry failed blocks
            if failed_indices:
                if DEBUG:
                    print(f"         🔄 Retrying {len(failed_indices)} blocks...")
                
                for idx in failed_indices:
                    text = original_texts[idx]
                    retry_result = translate_single_gemma(text, tgt_lang)
                    
                    is_valid, reason = validate_translation(text, retry_result, tgt_lang)
                    if is_valid:
                        results[idx] = retry_result
                        if DEBUG:
                            print(f"         ✅ Block {idx+1} Gemma3 retry success")
                    else:
                        # Use original text
                        results[idx] = text
                        if DEBUG:
                            print(f"         ❌ Block {idx+1} use original")
            
            return results
            
    except Exception as e:
        if DEBUG:
            print(f"      ⚠️ Batch translation error: {e}")
    
    # Fallback: block-by-block
    if DEBUG:
        print(f"      🔄 Batch failed, trying block-by-block...")
    
    for idx, (i, block, text, detected_lang) in enumerate(batch):
        result = translate_single_gemma(text, tgt_lang)
        is_valid, _ = validate_translation(text, result, tgt_lang)
        
        if is_valid:
            results[idx] = result
        else:
            # Use original text
            results[idx] = text
    
    return results


def parse_marker_response(response: str, expected_count: int, original_texts: list = None) -> list:
    """แยก response ด้วย ###BLOCKX### markers"""
    results = [''] * expected_count
    
    pattern = r'###BLOCK(\d+)###\s*(.+?)(?=###BLOCK\d+###|$)'
    matches = re.findall(pattern, response, re.DOTALL)
    
    for num_str, text in matches:
        idx = int(num_str) - 1
        if 0 <= idx < expected_count:
            cleaned = text.strip()
            cleaned = re.sub(r'^\*+|\*+$', '', cleaned)
            results[idx] = cleaned
    
    if not any(results):
        lines = response.strip().split('\n')
        for i, line in enumerate(lines):
            if i < expected_count:
                cleaned = re.sub(r'^###BLOCK\d+###\s*', '', line.strip())
                cleaned = re.sub(r'^\d+[\.\\)\-:]\s*', '', cleaned)
                cleaned = re.sub(r'^\*+|\*+$', '', cleaned)
                results[i] = cleaned if cleaned else ''
    
    return results


def validate_translation(original: str, translated: str, tgt_lang: str = None) -> tuple:
    """ตรวจสอบว่าผลลัพธ์การแปลถูกต้องหรือไม่"""
    if not translated:
        return False, "empty"
    
    prompt_fragments = [
        "Preserve all numbers", "Keep the numbering", "Output ONLY",
        "no explanations", "###BLOCK", "Translate each line",
        "IMPORTANT:", "formatting from the original"
    ]
    
    for fragment in prompt_fragments:
        if fragment.lower() in translated.lower():
            return False, "contains prompt"
    
    if len(original) > 50 and len(translated) < len(original) * 0.3:
        return False, "too short"
    
    if re.match(r'^[\d\.\s\-\:]+$', translated):
        return False, "numbers only"
    
    orig_clean = re.sub(r'^[·•\-\*\d\.\)\s]+', '', original).strip()
    trans_clean = re.sub(r'^[·•\-\*\d\.\)\s]+', '', translated).strip()
    if orig_clean == trans_clean:
        return False, "same as original (echo)"
    
    if tgt_lang:
        detected_lang = detect_language(translated)
        orig_lang = detect_language(original)
        if detected_lang == orig_lang and orig_lang != tgt_lang:
            return False, f"wrong language ({detected_lang})"
    
    return True, "ok"


def fix_number_prefix(original: str, translated: str, tgt_lang: str) -> str:
    """แก้ไขตัวเลขนำหน้าให้ถูกต้อง"""
    if not original or not translated:
        return translated
    
    number_pattern = r'^(\d+)[\.\)\:\-\s]+'
    thai_prefix_pattern = r'^((?:บทที่|ข้อที่|ตอนที่|หัวข้อที่|ข้อ)\s*\d+)[\.\)\:\s]*'
    eng_prefix_pattern = r'^((?:Chapter|Section|Part|Item|No\.?)\s*\d+)[\.\)\:\s]*'
    
    orig_number = None
    orig_prefix = None
    
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
    
    trans_match = re.match(number_pattern, translated)
    
    if orig_number is None:
        if trans_match:
            translated = re.sub(number_pattern, '', translated)
    else:
        if not trans_match:
            if tgt_lang == "eng_Latn":
                if match_thai:
                    if "บทที่" in orig_prefix:
                        translated = f"Chapter {orig_number}: {translated}"
                    elif "ข้อที่" in orig_prefix or "ข้อ" in orig_prefix:
                        translated = f"Item {orig_number}. {translated}"
                    else:
                        translated = f"{orig_number}. {translated}"
                else:
                    translated = f"{orig_number}. {translated}"
            else:
                if match_eng:
                    if "chapter" in orig_prefix.lower():
                        translated = f"บทที่ {orig_number} {translated}"
                    else:
                        translated = f"{orig_number}. {translated}"
                else:
                    translated = f"{orig_number}. {translated}"
        else:
            trans_number = trans_match.group(1)
            if trans_number != orig_number:
                translated = re.sub(number_pattern, f"{orig_number}. ", translated)
    
    return translated


# Stats tracking
translation_stats = {"translated": 0, "skipped": 0}


def translate_page_blocks(blocks: list, tgt_lang: str) -> list:
    """แปล blocks ด้วย Phi-3-Mini (batch 5)"""
    global translation_stats
    
    if not blocks:
        return blocks
    
    BATCH_SIZE = 5
    
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
    
    results = [None] * len(blocks)
    
    for i, block, text, detected_lang in already_target:
        results[i] = {
            **block,
            'translated': text,
            'detected_lang': detected_lang,
            'was_translated': False
        }
    
    if not to_translate:
        return results
    
    num_batches = (len(to_translate) + BATCH_SIZE - 1) // BATCH_SIZE
    
    if DEBUG:
        print(f"      📊 ต้องแปล: {len(to_translate)}, ข้าม: {len(already_target)}, batches: {num_batches}")
    
    for batch_idx in range(num_batches):
        start_idx = batch_idx * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, len(to_translate))
        batch = to_translate[start_idx:end_idx]
        
        if DEBUG:
            print(f"      🔄 Batch {batch_idx + 1}/{num_batches} ({len(batch)} blocks)")
        
        batch_results = translate_batch_gemma(batch, tgt_lang)
        
        for j, (i, block, text, detected_lang) in enumerate(batch):
            translated = batch_results[j] if j < len(batch_results) else None
            
            if translated and translated != text:
                translated = fix_number_prefix(text, translated, tgt_lang)
                translation_stats["translated"] += 1
            else:
                translated = text
                translation_stats["translated"] += 1
            
            results[i] = {
                **block,
                'translated': translated,
                'detected_lang': detected_lang,
                'was_translated': True
            }
    
    return results


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
    """คำนวณ font size และ wrap text ให้พอดี bbox"""
    detected_lang = detect_language(text)
    
    for size in range(max_font, min_font - 1, -1):
        font = get_font(size, detected_lang)
        wrapped = wrap_text(text, font, bbox_width, draw)
        
        total_height = 0
        for line in wrapped:
            line_bbox = draw.textbbox((0, 0), line, font=font)
            total_height += (line_bbox[3] - line_bbox[1]) + 2
        
        if total_height <= bbox_height:
            return font, wrapped
    
    font = get_font(min_font, detected_lang)
    wrapped = wrap_text(text, font, bbox_width, draw)
    return font, wrapped


def extract_text_blocks(doc, page_no: int) -> list:
    """ดึง text blocks จาก DoclingDocument"""
    blocks = []
    
    picture_text_refs = set()
    for pic in doc.pictures:
        for child in pic.children:
            if hasattr(child, '$ref'):
                picture_text_refs.add(child['$ref'])
            elif hasattr(child, 'self_ref'):
                picture_text_refs.add(child.self_ref)
    
    list_item_counter = 0
    
    for item in doc.texts:
        if item.label in [DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER]:
            continue
        
        if hasattr(item, 'self_ref') and item.self_ref in picture_text_refs:
            continue
        
        if hasattr(item, 'parent') and item.parent:
            parent_ref = item.parent.get('$ref', '') if isinstance(item.parent, dict) else getattr(item.parent, '$ref', '')
            if 'pictures' in str(parent_ref):
                continue
            
        if item.prov:
            for prov in item.prov:
                if prov.page_no == page_no:
                    text = item.text
                    
                    if str(item.label) == "DocItemLabel.LIST_ITEM" or "list_item" in str(item.label).lower():
                        marker = getattr(item, 'marker', None)
                        if marker:
                            text = f"{marker} {item.text}"
                        else:
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


def extract_tables(doc, page_no: int) -> list:
    """ดึงตารางจาก DoclingDocument"""
    tables = []
    
    for table in doc.tables:
        if table.prov:
            for prov in table.prov:
                if prov.page_no == page_no:
                    cells = []
                    if hasattr(table, 'data') and table.data:
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
    
    line_color = (0, 0, 0)
    
    for i in range(num_rows + 1):
        y = y1 + (i * cell_height)
        draw.line([(x1, y), (x2, y)], fill=line_color, width=1)
    
    for j in range(num_cols + 1):
        x = x1 + (j * cell_width)
        draw.line([(x, y1), (x, y2)], fill=line_color, width=1)
    
    padding = 4
    
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
    
    translated_cells = translate_table_cells(cells_to_translate, tgt_lang)
    
    for cell in translated_cells:
        row = cell['row']
        col = cell['col']
        translated = cell.get('translated', cell.get('text', ''))
        
        cx = x1 + (col * cell_width) + padding
        cy = y1 + (row * cell_height) + padding
        available_width = cell_width - (padding * 2)
        available_height = cell_height - (padding * 2)
        
        if available_width < 10 or available_height < 10:
            continue
        
        font_size = 18
        min_font_size = 10
        
        while font_size >= min_font_size:
            small_font = get_font(font_size)
            wrapped_lines = wrap_text(translated, small_font, available_width, draw)
            
            total_height = 0
            for line in wrapped_lines:
                line_bbox = draw.textbbox((0, 0), line, font=small_font)
                total_height += (line_bbox[3] - line_bbox[1]) + 2
            
            if total_height <= available_height:
                break
            
            font_size -= 1
        
        current_y = cy
        for line in wrapped_lines:
            line_bbox = draw.textbbox((0, 0), line, font=small_font)
            line_height = line_bbox[3] - line_bbox[1]
            
            if current_y + line_height <= cy + available_height:
                draw.text((cx, current_y), line, fill="black", font=small_font)
                current_y += line_height + 2


def translate_table_cells(cells: list, tgt_lang: str) -> list:
    """แปลทุก cell ในตารางด้วย Gemma2"""
    global total_translation_time, translation_stats
    
    if not cells:
        return cells
    
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
    
    results = [None] * len(cells)
    
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
    
    lines_text = []
    for idx, (i, cell, detected_lang) in enumerate(to_translate):
        lines_text.append(f"{idx + 1}. {cell['text']}")
    
    combined_text = "\n".join(lines_text)
    
    lang_names = {
        "eng_Latn": "English",
        "tha_Thai": "Thai",
    }
    target_name = lang_names.get(tgt_lang, tgt_lang)
    
    prompt = f"""Translate each line to {target_name}. Keep the numbering format (1. 2. 3.).
IMPORTANT: Preserve all original numbers from the source text.
Output ONLY the translations, no explanations.

{combined_text}"""
    
    start = time.time()
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": GEMMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2048}
            },
            timeout=120
        )
        
        total_translation_time += (time.time() - start)
        
        if resp.status_code == 200:
            response = resp.json().get("response", "").strip()
            translated_lines = parse_numbered_response(response, len(to_translate))
            
            for idx, (i, cell, detected_lang) in enumerate(to_translate):
                if idx < len(translated_lines):
                    translated = translated_lines[idx]
                    translation_stats["translated"] += 1
                else:
                    translated = cell['text']
                
                results[i] = {
                    **cell,
                    'translated': translated,
                    'detected_lang': detected_lang,
                    'was_translated': True
                }
            
            return results
            
    except Exception as e:
        print(f"   ⚠️ Table translation error: {e}")
    
    for i, cell, detected_lang in to_translate:
        results[i] = {
            **cell,
            'translated': cell['text'],
            'detected_lang': detected_lang,
            'was_translated': False
        }
    
    return results


def parse_numbered_response(response: str, expected_count: int) -> list:
    """แยก response ที่มีเลขลำดับ"""
    lines = response.strip().split('\n')
    results = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        cleaned = re.sub(r'^\d+[\.\\)\-:]\s*', '', line)
        if cleaned:
            results.append(cleaned)
        else:
            results.append(line)
    
    return results


def process_pdf_with_docling(pdf_path: str, tgt_lang: str):
    """Process PDF ด้วย Docling + Phi-3-Mini"""
    global total_translation_time, CURRENT_FONT_PATH
    total_translation_time = 0
    
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
    
    if DEBUG:
        import json
        json_path = os.path.join(LOG_DIR, "docling_output.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(doc.export_to_dict(), ensure_ascii=False, indent=2))
        print(f"   📝 Saved: {json_path}")
    
    num_pages = len(doc.pages)
    print(f"   📄 {num_pages} หน้า")
    
    images = []
    total_blocks = 0
    
    for page_no in range(1, num_pages + 1):
        print(f"\n{'='*50}")
        print(f"📖 หน้า {page_no}/{num_pages}")
        
        blocks = extract_text_blocks(doc, page_no)
        print(f"   📦 {len(blocks)} text blocks")
        total_blocks += len(blocks)
        
        tables = extract_tables(doc, page_no)
        if tables:
            print(f"   📊 {len(tables)} tables detected")
        
        if not blocks and not tables:
            continue
        
        if isinstance(doc.pages, dict):
            page = doc.pages.get(str(page_no)) or doc.pages.get(page_no)
        else:
            page = doc.pages[page_no]
        
        if DEBUG:
            print(f"   📏 Page size: {page.size.width} x {page.size.height}")
        
        page_width = int(page.size.width * (DPI / 72))
        page_height = int(page.size.height * (DPI / 72))
        
        canvas = Image.new('RGB', (page_width, page_height), 'white')
        draw = ImageDraw.Draw(canvas)
        
        if DEBUG:
            log_file = os.path.join(LOG_DIR, f"page_{page_no:03d}_blocks.txt")
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"Page {page_no} - Text Blocks\n")
                f.write("=" * 60 + "\n\n")
        
        print("   🤖 แปล (Phi-3-Mini)...")
        
        translated_blocks = translate_page_blocks(blocks, tgt_lang)
        
        scale = DPI / 72
        for i, block in enumerate(translated_blocks):
            if block is None:
                continue
            
            bbox = block['bbox']
            translated = block.get('translated', block.get('text', ''))
            detected_lang = block.get('detected_lang', 'unknown')
            was_translated = block.get('was_translated', False)
            
            bbox_tl = bbox.to_top_left_origin(page_height=page.size.height)
            
            x1 = int(bbox_tl.l * scale)
            y1 = int(bbox_tl.t * scale)
            x2 = int(bbox_tl.r * scale)
            y2 = int(bbox_tl.b * scale)
            
            box_width = x2 - x1
            box_height = y2 - y1
            
            if DEBUG:
                status = "TRANSLATED" if was_translated else "SKIPPED"
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"Block {i+1} [{status}] (detected: {detected_lang}): [{x1}, {y1}] - [{x2}, {y2}]\n")
                    f.write(f"  Label: {block['label']}\n")
                    f.write(f"  Original: {block.get('text', '')}\n")
                    f.write(f"  Result: {translated}\n\n")
            
            if box_width > 10 and box_height > 10:
                font, wrapped_lines = fit_text_to_bbox(
                    draw, translated, box_width, box_height
                )
                
                current_y = y1
                for line in wrapped_lines:
                    line_bbox = draw.textbbox((0, 0), line, font=font)
                    line_height = line_bbox[3] - line_bbox[1]
                    
                    if current_y + line_height <= y2:
                        draw.text((x1, current_y), line, font=font, fill="black")
                        current_y += line_height + 2
        
        scale = DPI / 72
        for table_data in tables:
            print(f"   📊 วาดตาราง {table_data['num_rows']}x{table_data['num_cols']}...")
            draw_table(draw, table_data, page.size.height, scale, get_font(12), tgt_lang, log_file)
        
        out_path = os.path.join(OUTPUT_DIR, f"translated_{page_no:03d}.png")
        canvas.save(out_path)
        images.append(out_path)
        print(f"   ✅ Saved: {out_path}")
    
    print(f"\n{'='*50}")
    print("📦 สร้าง PDF...")
    
    if images:
        import fitz
        
        pdf_doc = fitz.open()
        
        for img_path in images:
            pix = fitz.Pixmap(img_path)
            
            page_width = pix.width * 72 / DPI
            page_height = pix.height * 72 / DPI
            
            page = pdf_doc.new_page(width=page_width, height=page_height)
            
            rect = fitz.Rect(0, 0, page_width, page_height)
            page.insert_image(rect, pixmap=pix)
            
            pix = None
        
        pdf_out = os.path.join(OUTPUT_DIR, "translated_phi3.pdf")
        pdf_doc.save(pdf_out)
        pdf_doc.close()
        
        print(f"   📄 {pdf_out}")
    
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
    print("📄 PDF Translation with Docling + Gemma2 (v1.0)")
    print("=" * 60)
    print(f"   โมเดลแปล: {GEMMA_MODEL}")
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
    
    print("\n📥 ตรวจสอบ Ollama...")
    try:
        resp = requests.post(OLLAMA_URL, json={"model": GEMMA_MODEL, "prompt": "Hi", "stream": False}, timeout=60)
        if resp.status_code == 200:
            print(f"✅ Gemma2 พร้อม ({GEMMA_MODEL})")
    except Exception as e:
        print(f"❌ Ollama error: {e}")
        exit(1)
    
    # ===== ภาษาเป้าหมาย (เปลี่ยนตรงนี้) =====
    # ภาษาเป้าหมายที่รองรับ:
    #   eng_Latn  = English (อังกฤษ)
    #   tha_Thai  = Thai (ไทย)
    #   zho_Hans  = Chinese Simplified (จีนตัวย่อ)
    #   jpn_Jpan  = Japanese (ญี่ปุ่น)
    #   kor_Hang  = Korean (เกาหลี)
    # ==========================================
    process_pdf_with_docling(PDF_PATH, "eng_Latn")
