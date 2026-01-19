
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
