
import re
from typing import Tuple

def normalize_text(text: str) -> str:
    """ลบตัวอักษรขยะและจัดรูปแบบ"""
    if not text:
        return ""
    # ลบ control characters แต่เก็บ newline
    text = "".join(ch for ch in text if ch == "\n" or (ch.isprintable() and ord(ch) >= 32))
    result = text.strip()
    # แทนที่ multiple spaces
    result = re.sub(r' +', ' ', result)
    return result

def clean_text(text: str) -> str:
    """ทำความสะอาด text ก่อนส่งแปล"""
    if not text:
        return ""
    # ลบตัวอักษรแปลกๆ
    text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
    return text.strip()

def detect_language(text: str) -> str:
    """
    ตรวจจับภาษาหลักของข้อความ (Logic เดิม)
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

def should_translate(text: str, target_lang: str) -> Tuple[bool, str]:
    """
    เช็คว่าควรแปล block นี้หรือไม่
    Returns: (should_translate, detected_lang)
    """
    if not text or len(text.strip()) < 2:
        return False, "unknown"
        
    detected = detect_language(text)
    
    # ถ้าเป็นภาษาเป้าหมายอยู่แล้ว → ไม่ต้องแปล
    if detected == target_lang:
        return False, detected
    
    return True, detected


# ============================================
# Text Normalization Utilities (moved from render_service.py)
# ============================================

def normalize_punctuation(text: str) -> str:
    """แปลง fullwidth punctuation เป็น ascii เพื่อแก้ปัญหา font"""
    replacements = {
        '。': '.',
        '？': '?',
        '！': '!',
        '，': ',',
        '：': ':',
        '；': ';',
        '（': '(',
        '）': ')',
        '"': '"',
        '"': '"',
        ''': "'",
        ''': "'"
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text


def cleanup_llm_explanations(text: str) -> str:
    """Clean up English explanations from LLM output (same as frontend cleanup)"""
    original_text = text
    
    # Only remove SPECIFIC explanation patterns, not all English text
    text = re.sub(r'I made some changes.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'Here\'s a brief.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\*\*Explanation[^*]*\*\*.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'Let me know.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\*\*[A-Za-z\s:]+\*\*.*$', '', text, flags=re.DOTALL)
    
    # Remove common LLM prefixes
    text = re.sub(r'^(Translation:|Output:|Result:)\s*', '', text, flags=re.MULTILINE | re.IGNORECASE)
    
    # Remove bullet points with English explanations
    text = re.sub(r'(\n\s*\*\s+In BLOCK.*$)', '', text, flags=re.DOTALL)
    
    text = text.strip()
    
    if text != original_text:
        print(f"   🧹 Cleaned up LLM explanations for rendering")
    
    return text


def normalize_ocr_text(text: str) -> list:
    """
    แปลง OCR text เป็น structured paragraphs
    รักษา \\n และ \\n\\n
    Returns: List of {"type": "heading"|"paragraph", "text": str}
    """
    # Clean up markdown artifacts
    text = re.sub(r'```[a-z]*\n?', '', text)  # Remove code blocks
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # Remove bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)  # Remove italic
    text = re.sub(r'#+\s*', '', text)  # Remove heading markers
    
    # Split by double newline (paragraphs)
    paragraphs = text.split('\n\n')
    
    result = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # Check if it looks like a heading (short, no period at end)
        is_heading = len(para) < 100 and not para.endswith('.')
        
        result.append({
            "type": "heading" if is_heading else "paragraph",
            "text": para
        })
    
    return result


def is_ocr_flow_mode(page_data: dict) -> bool:
    """
    ตรวจสอบว่าเป็น OCR flow mode หรือไม่
    Return True ถ้า:
    - มี block เดียว
    - bbox ครอบเกือบทั้งหน้า (margin-based)
    """
    blocks = page_data.get("blocks", [])
    if len(blocks) != 1:
        return False
    
    block = blocks[0]
    bbox = block.get("bbox", {})
    page_width = page_data.get("width", 0)
    page_height = page_data.get("height", 0)
    
    if not all([bbox.get("x1"), bbox.get("y1"), bbox.get("x2"), bbox.get("y2")]):
        return False
    
    # Check if bbox covers most of page (margin-based from Typhoon OCR)
    margin_threshold = 100  # points
    
    is_near_left = bbox["x1"] < margin_threshold
    is_near_top = bbox["y1"] < margin_threshold
    is_near_right = (page_width - bbox["x2"]) < margin_threshold
    is_near_bottom = (page_height - bbox["y2"]) < margin_threshold
    
    return is_near_left and is_near_top and is_near_right and is_near_bottom
