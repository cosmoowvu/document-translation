
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
    ตรวจจับภาษาหลักของข้อความ
    รองรับ: ไทย, ญี่ปุ่น, จีน, เกาหลี, อังกฤษ (default)
    """
    if not text:
        return "unknown"
    
    # นับตัวอักษรแต่ละภาษา (ไม่นับ spaces, numbers, punctuation)
    thai = 0
    japanese = 0
    chinese = 0
    korean = 0
    latin = 0
    
    for c in text:
        if '\u0e00' <= c <= '\u0e7f':  # Thai
            thai += 1
        elif '\u3040' <= c <= '\u30ff':  # Japanese (Hiragana + Katakana)
            japanese += 1
        elif '\u4e00' <= c <= '\u9fff':  # CJK
            chinese += 1
        elif '\uac00' <= c <= '\ud7af':  # Korean
            korean += 1
        elif 'A' <= c <= 'Z' or 'a' <= c <= 'z':  # Latin letters only
            latin += 1
    
    # นับเฉพาะตัวอักษร (ไม่รวม spaces, numbers, symbols)
    total_letters = thai + japanese + chinese + korean + latin
    
    if total_letters == 0:
        return "unknown"
    
    # คำนวณสัดส่วน (ใช้ total_letters ไม่ใช่ len(text))
    lang_ratios = {
        "tha_Thai": thai / total_letters,
        "jpn_Jpan": japanese / total_letters,
        "zho_Hans": chinese / total_letters,
        "kor_Hang": korean / total_letters,
        "eng_Latn": latin / total_letters
    }
    
    # หาภาษาที่มีสัดส่วนสูงสุด (threshold 10% - ลดลงจาก 20%)
    max_lang = max(lang_ratios, key=lang_ratios.get)
    if lang_ratios[max_lang] > 0.1:
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
    seen_hashes = set()
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # Deduplication Check (Exact match after normalization)
        # Remove whitespace and punctuation for loose matching
        norm_para = re.sub(r'\s+', '', para).lower()
        if len(norm_para) > 10: # Only deduplicate meaningful blocks
            if norm_para in seen_hashes:
                print(f"   ⚠️ Skipping duplicate paragraph: {para[:30]}...")
                continue
            seen_hashes.add(norm_para)
        
        # Check if it looks like a heading (short, no period at end)
        is_heading = len(para) < 100 and not para.endswith('.')
        
        result.append({
            "type": "heading" if is_heading else "paragraph",
            "text": para
        })
    
    # ✅ Post-process: Merge incomplete HTML table fragments
    # Problem: LLM may break table with newlines like:
    # Para 1: "ตาราง <table>...<td>Benjaafar et al.</td>...</table>"
    # Para 2: "(2010)</td><td>...</td></tr></table>"
    # Solution: Detect and merge
    merged_result = []
    i = 0
    while i < len(result):
        current = result[i]
        current_text = current["text"]
        
        # Check if current paragraph ends with incomplete table (has <table> but ends mid-tag)
        # OR next paragraph starts with table fragment
        if i + 1 < len(result):
            next_para = result[i + 1]
            next_text = next_para["text"]
            
            # Pattern 1: Current has <table> but next starts with orphan closing tags
            # e.g., current: "...<td>Name</td>...</table>" next: "(2010)</td><td>..."
            has_table = '<table' in current_text.lower()
            next_starts_with_tag = re.match(r'^\s*[\(\)\w\s]*</t[dh]>', next_text, re.IGNORECASE)
            
            if has_table and next_starts_with_tag:
                print(f"   🔧 Merging incomplete table: paragraph {i+1} + {i+2}")
                # Merge next into current
                merged_text = current_text + " " + next_text
                merged_result.append({
                    "type": "paragraph",
                    "text": merged_text
                })
                i += 2  # Skip next
                continue
        
        merged_result.append(current)
        i += 1
    
    return merged_result



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
