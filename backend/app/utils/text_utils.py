"""
Text Utilities
ฟังก์ชันช่วยเหลือสำหรับจัดการข้อความ
"""
import re


def fix_ocr_numbers(text: str) -> str:
    """แก้ไข OCR อ่านตัวเลขผิด"""
    if not text:
        return text
    
    result = text
    result = re.sub(r'^a\.', '4.', result)
    result = re.sub(r'^a,', '4.', result)
    result = re.sub(r'(\d+\..*?)a\.', r'\g<1>4.', result)
    result = re.sub(r'^g\.', '9.', result)
    result = re.sub(r'^g,', '9.', result)
    result = re.sub(r'(\d)O(\d)', r'\g<1>0\g<2>', result)
    result = re.sub(r'(\d)O\b', r'\g<1>0', result)
    result = re.sub(r'\bO(\d)', r'0\g<1>', result)
    result = re.sub(r'(\d)l(\d)', r'\g<1>1\g<2>', result)
    
    return result


def get_ending_punctuation(text: str) -> str:
    """ดึงเครื่องหมายวรรคตอนท้ายประโยค"""
    text = text.strip()
    if text and text[-1] in '.,!?;:':
        return text[-1]
    return ""


def remove_unwanted_punctuation(original: str, translated: str) -> str:
    """ลบเครื่องหมายวรรคตอนท้ายที่ไม่มีในต้นฉบับ"""
    if not translated:
        return translated
    
    orig_ending = get_ending_punctuation(original)
    trans_ending = get_ending_punctuation(translated)
    
    if not orig_ending and trans_ending:
        translated = translated.rstrip()
        while translated and translated[-1] in '.,!?;:':
            translated = translated[:-1]
    
    return translated.strip()


def clean_translation_response(text: str) -> str:
    """ลบ prefix ที่ model อาจใส่มา"""
    if not text:
        return text
    
    result = re.sub(r'^(Translation:|English:|Thai:)\s*', '', text, flags=re.IGNORECASE)
    return result.strip()
