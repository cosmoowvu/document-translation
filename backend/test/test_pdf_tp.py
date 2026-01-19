"""
PDF Translation with Layout: PaddleOCR + Typhoon Translate (via Ollama)
- ใช้ PaddleOCR สำหรับ OCR + ตำแหน่ง
- ใช้ Typhoon Translate 4B ผ่าน Ollama สำหรับแปลภาษา
- แปลทั้งหน้าเพื่อให้ได้บริบท
- เก็บ layout ตำแหน่งเดิม
"""
import torch
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF
import cv2
import os
import time
import requests
import re
from paddleocr import PaddleOCR
import numpy as np

# ===== ตั้งค่า =====
PDF_PATH = "./test.pdf"
OUTPUT_DIR = "./output_images/pdf_typhoon"
DPI = 150

# Font sizes by type
FONT_SIZE_TITLE = 28
FONT_SIZE_SUBTITLE = 22
FONT_SIZE_BODY = 18
FONT_SIZE_SMALL = 14

# Margins
DEFAULT_LEFT_MARGIN = 50

# Ollama settings
OLLAMA_URL = "http://localhost:11434/api/generate"
TYPHOON_MODEL = "scb10x/typhoon-translate1.5-4b"

# ===== Timing =====
total_translation_time = 0

# ===== โหลด Models =====
print("=" * 60)
print("🌪️ PDF Translation: PaddleOCR + Typhoon Translate")
print("=" * 60)

print("\n📥 กำลังโหลด PaddleOCR...")
ocr_engine = PaddleOCR(lang='th')
print("✅ โหลด PaddleOCR สำเร็จ")

print("\n📥 ตรวจสอบ Ollama + Typhoon...")
try:
    test_response = requests.post(
        OLLAMA_URL,
        json={"model": TYPHOON_MODEL, "prompt": "Hello", "stream": False},
        timeout=180
    )
    if test_response.status_code == 200:
        print(f"✅ Typhoon Translate พร้อมใช้งาน ({TYPHOON_MODEL})")
    else:
        print(f"⚠️ Ollama ตอบกลับ status: {test_response.status_code}")
except Exception as e:
    print(f"❌ ไม่สามารถเชื่อมต่อ Ollama: {e}")
    print("   กรุณารัน: ollama serve")
    print(f"   และ: ollama pull {TYPHOON_MODEL}")
    exit(1)


def is_number_only(text: str) -> bool:
    """ตรวจสอบว่าเป็นตัวเลขอย่างเดียวหรือไม่"""
    cleaned = text.strip()
    if not cleaned:
        return False
    number_pattern = r'^[\d\s\.,\-/%]+$'
    return bool(re.match(number_pattern, cleaned))


def extract_bullet_or_number(text: str) -> tuple:
    """แยก bullet/number prefix ออกจากข้อความ"""
    text = text.strip()
    
    patterns = [
        r'^(•\s*)',
        r'^(●\s*)',
        r'^(○\s*)',
        r'^(▪\s*)',
        r'^(▫\s*)',
        r'^(-\s+)',
        r'^(\d+\.\s*)',
        r'^(\d+\)\s*)',
        r'^(\([a-zA-Z]\)\s*)',
        r'^([a-zA-Z]\.\s*)',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            prefix = match.group(1)
            remaining = text[len(prefix):].strip()
            return (prefix, remaining)
    
    return ("", text)


def should_skip_translation(text: str) -> bool:
    """ตรวจสอบว่าควรข้ามการแปลหรือไม่"""
    cleaned = text.strip()
    
    if is_number_only(cleaned):
        return True
    
    if len(cleaned) <= 2:
        return True
    
    return False


def fix_ocr_numbers(text: str) -> str:
    """Post-processing แก้ไข OCR อ่านตัวเลขผิด"""
    if not text:
        return text
    
    result = text
    result = re.sub(r'^a\.', '4.', result)
    result = re.sub(r'^a,', '4.', result)
    result = re.sub(r'^g\.', '9.', result)
    result = re.sub(r'^g,', '9.', result)
    result = re.sub(r'(\d)O(\d)', r'\g<1>0\g<2>', result)
    result = re.sub(r'(\d)O\b', r'\g<1>0', result)
    result = re.sub(r'\bO(\d)', r'0\g<1>', result)
    result = re.sub(r'(\d)l(\d)', r'\g<1>1\g<2>', result)
    
    return result


def translate_full_page_typhoon(lines_text: list, tgt_lang: str, max_retries: int = 2) -> list:
    """
    แปลทั้งหน้าพร้อมกัน เพื่อให้ได้บริบท
    ใช้ ###LINE1### separator
    """
    global total_translation_time
    
    if not lines_text:
        return []
    
    expected_count = len(lines_text)
    
    for attempt in range(max_retries + 1):
        # สร้างข้อความรวมพร้อม marker
        combined_text = ""
        for i, text in enumerate(lines_text):
            combined_text += f"###LINE{i+1}### {text}\n"
        
        combined_text = combined_text.strip()
        
        # สร้าง prompt
        if tgt_lang == "eng_Latn":
            prompt = f"""Translate the following Thai text into English.
IMPORTANT: Keep ALL line markers ###LINE1###, ###LINE2###, etc. exactly as they are.
Each line MUST have its marker. Do not skip or merge lines.
Output ONLY the translation with markers, no explanations.

{combined_text}"""
        else:
            prompt = f"""Translate the following English text into Thai.
IMPORTANT: Keep ALL line markers ###LINE1###, ###LINE2###, etc. exactly as they are.
Each line MUST have its marker. Do not skip or merge lines.
Output ONLY the translation with markers, no explanations.

{combined_text}"""
        
        start_time = time.time()
        
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": TYPHOON_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 2048,
                    }
                },
                timeout=120
            )
            
            elapsed = time.time() - start_time
            total_translation_time += elapsed
            
            if response.status_code == 200:
                result = response.json()
                translated_text = result.get("response", "").strip()
                parsed_lines = parse_translated_lines(translated_text, expected_count)
                
                # Validate
                non_empty_count = sum(1 for line in parsed_lines if line.strip())
                
                if non_empty_count >= expected_count * 0.8:
                    if attempt > 0:
                        print(f"      ✅ Retry สำเร็จ (attempt {attempt + 1})")
                    return parsed_lines
                else:
                    if attempt < max_retries:
                        print(f"      ⚠️ ได้แค่ {non_empty_count}/{expected_count} บรรทัด - retry...")
                    continue
            else:
                print(f"      ⚠️ Typhoon error: {response.status_code}")
                if attempt < max_retries:
                    continue
                return [""] * expected_count
                
        except Exception as e:
            elapsed = time.time() - start_time
            total_translation_time += elapsed
            print(f"      ⚠️ Typhoon error: {e}")
            if attempt < max_retries:
                continue
            return [""] * expected_count
    
    # หมด retry - fallback แปลทีละบรรทัด
    print(f"      ⚠️ หมด retry - fallback แปลทีละบรรทัด")
    return translate_lines_individually(lines_text, tgt_lang)


def translate_lines_individually(lines_text: list, tgt_lang: str) -> list:
    """Fallback: แปลทีละบรรทัด"""
    global total_translation_time
    results = []
    
    for text in lines_text:
        if not text.strip():
            results.append("")
            continue
        
        if tgt_lang == "eng_Latn":
            prompt = f"Translate into English: {text}"
        else:
            prompt = f"Translate into Thai: {text}"
        
        start_time = time.time()
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": TYPHOON_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 256}
                },
                timeout=60
            )
            elapsed = time.time() - start_time
            total_translation_time += elapsed
            
            if response.status_code == 200:
                result = response.json()
                translated = result.get("response", "").strip()
                results.append(translated if translated else text)
            else:
                results.append(text)
        except:
            results.append(text)
    
    return results


def parse_translated_lines(translated_text: str, expected_count: int) -> list:
    """Parse ผลแปลที่มี marker กลับเป็น list"""
    result = []
    
    # หา marker ###LINE1###, ###LINE2###, ...
    pattern = r'###LINE(\d+)###\s*([^#\n]+)'
    matches = re.findall(pattern, translated_text)
    
    if matches:
        line_dict = {}
        for num, text in matches:
            line_dict[int(num)] = text.strip()
        
        for i in range(1, expected_count + 1):
            if i in line_dict:
                result.append(line_dict[i])
            else:
                result.append("")
        
        return result
    
    # Fallback - แยกด้วย newline
    lines = translated_text.strip().split('\n')
    
    cleaned_lines = []
    for line in lines:
        cleaned = re.sub(r'###LINE\d+###\s*', '', line).strip()
        if cleaned:
            cleaned_lines.append(cleaned)
    
    for i in range(expected_count):
        if i < len(cleaned_lines):
            result.append(cleaned_lines[i])
        else:
            result.append("")
    
    return result


def get_font(size: int):
    """หา font ที่รองรับภาษาไทยและอังกฤษ"""
    font_paths = [
        "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except:
                continue
    return ImageFont.load_default()


def detect_text_type(bbox: list, text: str, page_width: int, page_height: int) -> str:
    """ตรวจสอบประเภทของข้อความจาก bbox และตำแหน่ง"""
    x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
    
    center_x = (x1 + x2) / 2
    page_center = page_width / 2
    
    is_centered = abs(center_x - page_center) < page_width * 0.15
    
    has_bullet = bool(re.match(r'^[•●○▪▫\-]\s*', text))
    has_number = bool(re.match(r'^\d+[\.\\)]\s*', text))
    
    if has_bullet or has_number:
        return 'bullet'
    
    if is_centered and len(text) < 50:
        if y1 < page_height * 0.2:
            return 'title'
        return 'subtitle'
    
    return 'body'


def get_font_size_for_type(text_type: str) -> int:
    """กำหนด font size ตามประเภท"""
    sizes = {
        'title': FONT_SIZE_TITLE,
        'subtitle': FONT_SIZE_SUBTITLE,
        'bullet': FONT_SIZE_BODY,
        'body': FONT_SIZE_BODY,
    }
    return sizes.get(text_type, FONT_SIZE_BODY)


def extract_text_with_paddle(image_path: str):
    """ใช้ PaddleOCR ดึงข้อความและตำแหน่ง"""
    result = ocr_engine.predict(image_path)
    
    elements = []
    
    # PaddleOCR v3.3.x: result เป็น list ที่มี OCRResult object
    if result and len(result) > 0:
        ocr_result = result[0]  # ดึง OCRResult object ตัวแรก
        
        # ดึงข้อมูลจาก OCRResult
        texts = ocr_result.get('rec_texts', []) if hasattr(ocr_result, 'get') else getattr(ocr_result, 'rec_texts', [])
        scores = ocr_result.get('rec_scores', []) if hasattr(ocr_result, 'get') else getattr(ocr_result, 'rec_scores', [])
        boxes = ocr_result.get('dt_polys', []) if hasattr(ocr_result, 'get') else getattr(ocr_result, 'dt_polys', [])
        
        if texts and boxes:
            for i in range(len(texts)):
                text = texts[i] if i < len(texts) else ""
                score = scores[i] if i < len(scores) else 0.5
                bbox_points = boxes[i] if i < len(boxes) else None
                
                if text and text.strip() and bbox_points is not None and score >= 0.3:
                    try:
                        x_coords = [p[0] for p in bbox_points]
                        y_coords = [p[1] for p in bbox_points]
                        
                        x1 = int(min(x_coords))
                        y1 = int(min(y_coords))
                        x2 = int(max(x_coords))
                        y2 = int(max(y_coords))
                        
                        elements.append({
                            'bbox': [x1, y1, x2, y2],
                            'text': text.strip(),
                            'confidence': score,
                            'x1': x1,
                            'y1': y1,
                            'x2': x2,
                            'y2': y2,
                            'height': y2 - y1
                        })
                    except Exception as e:
                        print(f"      ⚠️ Error parsing bbox: {e}")
                        continue
    
    elements.sort(key=lambda x: (x['y1'], x['x1']))
    
    return elements


def group_elements_by_line(elements: list, y_threshold: int = 15) -> list:
    """รวม elements ที่อยู่ในบรรทัดเดียวกัน"""
    if not elements:
        return []
    
    lines = []
    current_line = [elements[0]]
    current_y = elements[0]['y1']
    
    for el in elements[1:]:
        if abs(el['y1'] - current_y) <= y_threshold:
            current_line.append(el)
        else:
            lines.append(current_line)
            current_line = [el]
            current_y = el['y1']
    
    if current_line:
        lines.append(current_line)
    
    merged = []
    for line in lines:
        line.sort(key=lambda x: x['x1'])
        
        x1 = min(el['x1'] for el in line)
        y1 = min(el['y1'] for el in line)
        x2 = max(el['x2'] for el in line)
        y2 = max(el['y2'] for el in line)
        
        combined_text = ' '.join([el['text'] for el in line])
        
        merged.append({
            'bbox': [x1, y1, x2, y2],
            'text': combined_text,
            'x1': x1,
            'y1': y1,
            'x2': x2,
            'y2': y2,
            'height': y2 - y1
        })
    
    return merged


def process_page(image_path: str, output_path: str, 
                 src_lang: str, tgt_lang: str, width: int, height: int):
    """ประมวลผลหน้าเดียว"""
    
    print("   🔍 OCR (PaddleOCR)...")
    elements = extract_text_with_paddle(image_path)
    merged_elements = group_elements_by_line(elements)
    
    print(f"   📏 พบ {len(merged_elements)} บรรทัด")
    
    if not merged_elements:
        new_image = Image.new('RGB', (width, height), 'white')
        new_image.save(output_path)
        return 0
    
    # ตรวจสอบประเภทของแต่ละ element
    for el in merged_elements:
        el['type'] = detect_text_type(el['bbox'], el['text'], width, height)
    
    # ดึงและแก้ไข text
    original_texts = [fix_ocr_numbers(el['text']) for el in merged_elements]
    
    # แปลทั้งหน้า
    print("   🌪️ แปลภาษา (Typhoon Full Context)...")
    translated_texts = translate_full_page_typhoon(original_texts, tgt_lang)
    
    # สร้างภาพพื้นขาวใหม่
    new_image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(new_image)
    
    # วาดข้อความแปลในตำแหน่งเดิม
    for i, (el, translated) in enumerate(zip(merged_elements, translated_texts)):
        if not translated:
            continue
        
        text_type = el['type']
        font_size = get_font_size_for_type(text_type)
        font = get_font(font_size)
        
        y = el['y1']
        
        if text_type in ['title', 'subtitle']:
            text_bbox = draw.textbbox((0, 0), translated, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            x = (width - text_width) // 2
        else:
            x = max(el['x1'], DEFAULT_LEFT_MARGIN)
        
        draw.text((x, y), translated, fill='black', font=font)
    
    new_image.save(output_path)
    
    return len(merged_elements)


def full_pipeline(pdf_path: str, src_lang: str, tgt_lang: str):
    """Pipeline เต็ม"""
    global total_translation_time
    total_translation_time = 0
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    pipeline_start_time = time.time()
    
    print(f"\n📄 เปิด PDF: {pdf_path}")
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"📑 จำนวนหน้า: {total_pages}")
    
    zoom = DPI / 72
    matrix = fitz.Matrix(zoom, zoom)
    
    translated_images = []
    total_lines = 0
    
    for page_num in range(total_pages):
        print(f"\n{'='*60}")
        print(f"📖 หน้า {page_num + 1}/{total_pages}")
        print(f"{'='*60}")
        
        page = doc[page_num]
        pix = page.get_pixmap(matrix=matrix)
        
        original_path = os.path.join(OUTPUT_DIR, f"original_{page_num+1:03d}.png")
        pix.save(original_path)
        print(f"   📷 บันทึกรูปต้นฉบับ")
        
        width, height = pix.width, pix.height
        
        translated_path = os.path.join(OUTPUT_DIR, f"translated_{page_num+1:03d}.png")
        num_lines = process_page(
            original_path, translated_path, 
            src_lang, tgt_lang, width, height
        )
        total_lines += num_lines
        print(f"   ✅ บันทึกรูปแปล ({num_lines} บรรทัด)")
        
        translated_images.append(translated_path)
    
    doc.close()
    
    # รวมเป็น PDF
    print(f"\n{'='*60}")
    print("📦 กำลังรวมเป็น PDF...")
    print(f"{'='*60}")
    
    images = []
    for path in translated_images:
        img = Image.open(path).convert('RGB')
        images.append(img)
    
    output_pdf = os.path.join(OUTPUT_DIR, "translated_typhoon.pdf")
    images[0].save(
        output_pdf,
        "PDF",
        resolution=100.0,
        save_all=True,
        append_images=images[1:]
    )
    
    for img in images:
        img.close()
    
    pipeline_elapsed = time.time() - pipeline_start_time
    
    print(f"\n🎉 สร้างไฟล์สำเร็จ: {output_pdf}")
    
    # สรุปเวลา
    print(f"\n{'='*60}")
    print("⏱️ สรุป:")
    print(f"{'='*60}")
    print(f"   📊 เวลาแปลทั้งหมด: {total_translation_time:.1f} วินาที ({total_translation_time/60:.1f} นาที)")
    print(f"   📊 เวลา pipeline ทั้งหมด: {pipeline_elapsed:.1f} วินาที ({pipeline_elapsed/60:.1f} นาที)")
    print(f"   📊 จำนวนบรรทัดทั้งหมด: {total_lines}")
    print(f"   📊 จำนวนหน้า: {total_pages} หน้า")
    if total_pages > 0:
        print(f"   📊 เฉลี่ยต่อหน้า: {total_translation_time/total_pages:.2f} วินาที")
    
    return output_pdf


# ===== รันทดสอบ =====
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🌪️ PDF Translation: PaddleOCR + Typhoon Translate")
    print("=" * 60)
    print(f"   โมเดล: {TYPHOON_MODEL}")
    print("   เฉพาะ: ไทย ↔ อังกฤษ")
    print("   OCR: PaddleOCR")
    print("   พัฒนาโดย: SCB10X")
    print("   Features:")
    print("   ✅ Layout Preservation")
    print("   ✅ Full Page Context Translation")
    print("   ✅ Thai ↔ English Specialized")
    print("=" * 60)
    
    if not os.path.exists(PDF_PATH):
        print(f"⚠️ ไม่พบ {PDF_PATH}")
        exit(1)
    
    result = full_pipeline(
        pdf_path=PDF_PATH,
        src_lang="tha_Thai",
        tgt_lang="eng_Latn"
    )
    
    print("\n" + "=" * 60)
    print("🎉 เสร็จสิ้น!")
    print(f"📄 PDF: {result}")
    print("=" * 60)
