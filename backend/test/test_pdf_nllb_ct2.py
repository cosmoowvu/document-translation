"""
PDF Translation: Docling OCR + NLLB-CT2 Translation
- ใช้ Docling สำหรับ OCR ที่แม่นยำ (เหมือน test_pdf_docling.py)
- ใช้ NLLB-CT2 สำหรับการแปลภาษา (เร็ว, แม่นยำ)
"""
import os
import sys
import time
import re
import unicodedata

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
PDF_PATH = "./test_en2.pdf"
OUTPUT_DIR = "./output_images/pdf_nllb_ct2"
DPI = 150

# NLLB-CT2 settings
NLLB_MODEL_DIR = "../models/nllb-1.3b-ct2"
NLLB_TOKENIZER = "facebook/nllb-200-1.3B"

# Font
FONT_PATH = "C:/Windows/Fonts/tahoma.ttf"

# Debug
DEBUG = True
LOG_DIR = "./output_images/pdf_nllb_ct2/logs"

# Timing
total_translation_time = 0

# ===== Load NLLB Model =====
print("📥 กำลังโหลด NLLB-CT2...")
nllb_tokenizer = AutoTokenizer.from_pretrained(NLLB_TOKENIZER)
nllb_device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
nllb_translator = ctranslate2.Translator(NLLB_MODEL_DIR, device=nllb_device, compute_type="int8")
print(f"✅ NLLB พร้อม ({nllb_device.upper()})")


def get_font(size=16):
    if os.path.exists(FONT_PATH):
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except:
            pass
    return ImageFont.load_default()


def normalize_ocr_text(text: str) -> str:
    """
    Normalize ข้อความหลัง OCR
    แก้ไขอักขระพิเศษที่ OCR มักอ่านผิด
    """
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


# Stats tracking
translation_stats = {"translated": 0, "skipped": 0}


def translate_page_blocks(blocks: list, tgt_lang: str) -> list:
    """
    แปล blocks ด้วย NLLB-CT2 (batch processing)
    """
    global translation_stats
    
    if not blocks:
        return blocks
    
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
    
    if DEBUG:
        print(f"      📊 ต้องแปล: {len(to_translate)}, ข้าม: {len(already_target)}")
    
    # หา source language (ใช้จาก block แรก)
    src_lang = to_translate[0][3] if to_translate[0][3] != "unknown" else "tha_Thai"
    
    # ดึง texts ที่ต้องแปล
    texts_to_translate = [text for (i, block, text, detected_lang) in to_translate]
    
    # แปลด้วย NLLB batch
    translated_texts = translate_batch_nllb(texts_to_translate, src_lang, tgt_lang)
    
    # ใส่ผลลัพธ์
    for j, (i, block, text, detected_lang) in enumerate(to_translate):
        translated = translated_texts[j] if j < len(translated_texts) else text
        
        if translated and translated != text:
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
    for size in range(max_font, min_font - 1, -1):
        font = get_font(size)
        wrapped = wrap_text(text, font, bbox_width, draw)
        
        # คำนวณความสูงรวม
        total_height = 0
        for line in wrapped:
            line_bbox = draw.textbbox((0, 0), line, font=font)
            total_height += (line_bbox[3] - line_bbox[1]) + 2
        
        if total_height <= bbox_height:
            return font, wrapped
    
    # ถ้าใหญ่สุดก็ยังไม่พอ ใช้ min font
    font = get_font(min_font)
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


def translate_table_cells(cells: list, tgt_lang: str) -> list:
    """
    แปลทุก cell ในตารางด้วย NLLB-CT2
    """
    global translation_stats
    
    if not cells:
        return cells
    
    # แยก cells ที่ต้องแปล vs ไม่ต้องแปล
    to_translate = []
    already_target = []
    
    for i, cell in enumerate(cells):
        text = normalize_ocr_text(cell['text'])
        need_translate, detected_lang = should_translate(text, tgt_lang)
        
        if need_translate:
            to_translate.append((i, cell, text, detected_lang))
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
    
    # หา source language
    src_lang = to_translate[0][3] if to_translate[0][3] != "unknown" else "tha_Thai"
    
    # ดึง texts ที่ต้องแปล
    texts_to_translate = [text for (i, cell, text, detected_lang) in to_translate]
    
    # แปลด้วย NLLB batch
    translated_texts = translate_batch_nllb(texts_to_translate, src_lang, tgt_lang)
    
    # Map กลับไป cells
    for idx, (i, cell, text, detected_lang) in enumerate(to_translate):
        if idx < len(translated_texts):
            translated = translated_texts[idx]
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


def draw_table(draw, table_data, page_height, scale, font, tgt_lang):
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
    
    # แปลทั้งตารางด้วย NLLB
    translated_cells = translate_table_cells(cells_to_translate, tgt_lang)
    
    # วาดแต่ละ cell
    for cell in translated_cells:
        if cell is None:
            continue
            
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
        font_size = 18
        min_font_size = 10
        
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


def process_pdf_with_docling(pdf_path: str, tgt_lang: str):
    """Process PDF ด้วย Docling OCR + NLLB Translation"""
    global total_translation_time
    total_translation_time = 0
    
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
        
        # ดึงขนาดหน้า
        page = doc.pages[page_no]
        page_width = int(page.size.width * (DPI / 72))
        page_height = int(page.size.height * (DPI / 72))
        
        # สร้าง white canvas
        canvas = Image.new('RGB', (page_width, page_height), 'white')
        draw = ImageDraw.Draw(canvas)
        
        # Debug log
        if DEBUG:
            log_file = os.path.join(LOG_DIR, f"page_{page_no:03d}_blocks.txt")
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"Page {page_no} - Text Blocks\n")
                f.write("=" * 60 + "\n\n")
        
        print("   🤖 แปล (NLLB-CT2 batch)...")
        
        # แปลทั้งหน้าด้วย NLLB batch
        translated_blocks = translate_page_blocks(blocks, tgt_lang)
        
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
            if DEBUG:
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
            draw_table(draw, table_data, page.size.height, scale, get_font(12), tgt_lang)
        
        # บันทึก
        out_path = os.path.join(OUTPUT_DIR, f"translated_{page_no:03d}.png")
        canvas.save(out_path)
        images.append(out_path)
        print(f"   ✅ Saved: {out_path}")
    
    # สร้าง PDF
    print(f"\n{'='*50}")
    print("📦 สร้าง PDF...")
    
    if images:
        imgs = [Image.open(p).convert('RGB') for p in images]
        pdf_out = os.path.join(OUTPUT_DIR, "translated_nllb_ct2.pdf")
        imgs[0].save(pdf_out, "PDF", resolution=100.0, save_all=True, append_images=imgs[1:])
        
        for img in imgs:
            img.close()
        
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
    print("📄 PDF Translation: Docling OCR + NLLB-CT2")
    print("=" * 60)
    print(f"   โมเดลแปล: NLLB-200-1.3B (int8 quantized)")
    print(f"   Engine: CTranslate2 ({nllb_device.upper()})")
    print("   OCR: Docling (IBM Research)")
    print("   Features:")
    print("   ✅ Block-based extraction (Docling)")
    print("   ✅ Layout-aware understanding")
    print("   ✅ NLLB batch translation (เร็ว)")
    print("   ✅ Auto text wrapping")
    print("   ✅ White canvas output")
    print("=" * 60)
    
    if not os.path.exists(PDF_PATH):
        print(f"❌ ไม่พบ: {PDF_PATH}")
        exit(1)
    
    process_pdf_with_docling(PDF_PATH, "tha_Thai")
