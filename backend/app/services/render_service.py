"""
Render Service
วาดข้อความแปลลงบน canvas ตาม bounding box
"""
import os
import re
from typing import Dict, Any, List, Tuple
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

from app.config import settings


class RenderService:
    def __init__(self):
        self.dpi = settings.DPI
        self.font_path = settings.FONT_PATH
    
    def get_font(self, size: int = 16) -> ImageFont.FreeTypeFont:
        """โหลด font"""
        if os.path.exists(self.font_path):
            try:
                return ImageFont.truetype(self.font_path, size)
            except:
                pass
        return ImageFont.load_default()
    
    def wrap_text(self, text: str, font, max_width: int, draw) -> List[str]:
        """ตัดคำให้พอดี width - รองรับภาษาไทยและภาษาที่ไม่มีช่องว่าง"""
        # ตรวจสอบว่าเป็นภาษาที่ไม่มีช่องว่าง (Thai, Chinese, Japanese)
        has_cjk = bool(re.search(r'[\u0E00-\u0E7F\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3040-\u309F\u30A0-\u30FF]', text))
        
        if has_cjk or len(text.split()) < 3:  # ถ้ามีภาษา CJK หรือมีคำน้อยมาก
            # Character-based wrapping for Thai/CJK
            lines = []
            current_line = ""
            
            for char in text:
                test_line = current_line + char
                bbox = draw.textbbox((0, 0), test_line, font=font)
                width = bbox[2] - bbox[0]
                
                if width <= max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = char
            
            if current_line:
                lines.append(current_line)
            
            return lines if lines else [text]
        
        # Word-based wrapping for languages with spaces (English, etc.)
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
    
    def fit_text_to_bbox(self, draw, text: str, bbox_width: int, bbox_height: int,
                         max_font: int = 36, min_font: int = 12) -> Tuple[ImageFont.FreeTypeFont, List[str]]:
        """คำนวณ font size และ wrap text ให้พอดี bbox"""
        # ลด max font สำหรับข้อความยาว
        text_length = len(text)
        if text_length > 200:
            max_font = min(max_font, 24)
        elif text_length > 100:
            max_font = min(max_font, 28)
        
        for size in range(max_font, min_font - 1, -1):
            font = self.get_font(size)
            wrapped = self.wrap_text(text, font, bbox_width, draw)
            
            # คำนวณความสูงรวม
            total_height = 0
            for line in wrapped:
                line_bbox = draw.textbbox((0, 0), line, font=font)
                total_height += (line_bbox[3] - line_bbox[1]) + 3  # เพิ่ม line spacing
            
            if total_height <= bbox_height:
                return font, wrapped
        
        # ใช้ min font และ warn ถ้า overflow
        font = self.get_font(min_font)
        wrapped = self.wrap_text(text, font, bbox_width, draw)
        
        # Check overflow
        total_height = sum((draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1]) + 3 for line in wrapped)
        if total_height > bbox_height:
            print(f"   ⚠️ Text overflow: {total_height}px > {bbox_height}px (text length: {text_length} chars)")
        
        return font, wrapped
    
    def normalize_punctuation(self, text: str) -> str:
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
            '“': '"',
            '”': '"',
            '‘': "'",
            '’': "'"
        }
        for k, v in replacements.items():
            text = text.replace(k, v)
        return text
    
    def cleanup_llm_explanations(self, text: str) -> str:
        """Clean up English explanations from LLM output (same as frontend cleanup)"""
        original_text = text
        
        # Only remove SPECIFIC explanation patterns, not all English text
        # Remove explanations that start after Thai text
        text = re.sub(r'I made some changes.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'Here\'s a brief.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'\*\*Explanation[^*]*\*\*.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'Let me know.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'\*\*[A-Za-z\s:]+\*\*.*$', '', text, flags=re.DOTALL)
        
        # Remove common LLM prefixes (but not the content after them)
        text = re.sub(r'^(Translation:|Output:|Result:)\s*', '', text, flags=re.MULTILINE | re.IGNORECASE)
        
        # Remove bullet points with English explanations (starts with "* In BLOCK")
        text = re.sub(r'(\n\s*\*\s+In BLOCK.*$)', '', text, flags=re.DOTALL)
        
        # ✅ REMOVED: Don't remove all English sentences - they might be valid translations!
        # The old code removed lines starting with [A-Z][a-z]+ which deleted valid English translations
        
        text = text.strip()
        
        # Log if cleanup made changes
        if text != original_text:
            print(f"   🧹 Cleaned up LLM explanations for rendering")
            print(f"      Before: {original_text[:80]}...")
            print(f"      After:  {text[:80]}...")
        
        return text


    def render_page(self, page_data: Dict, page_no: int) -> Image.Image:
        """Render หน้าเดียว (blocks + tables)"""
        scale = self.dpi / 72
        width = int(page_data["width"] * scale)
        height = int(page_data["height"] * scale)
        
        print(f"   🎨 Rendering page {page_no}: {width}x{height}px (scale={scale:.2f}, DPI={self.dpi})")
        
        # สร้าง white canvas
        canvas = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(canvas)
        
        # คำนวณ Font Multiplier (Smart Scaling)
        # เปรียบเทียบความกว้างจริงกับความกว้างมาตรฐาน A4 (ที่ DPI เดียวกัน)
        # A4 width ~ 8.27 inches
        reference_width = self.dpi * 8.27
        font_multiplier = max(1.0, width / reference_width)
        
        # ปรับค่า Font config ตาม multiplier
        scaled_max = int(36 * font_multiplier)
        scaled_min = int(12 * font_multiplier)
        line_spacing = int(2 * font_multiplier)
        
        # Render text blocks
        rendered_count = 0
        for idx, block in enumerate(page_data["blocks"]):
            text = block["text"]
            
            # ✅ Cleanup LLM explanations before rendering
            text = self.cleanup_llm_explanations(text)
            
            # Normalize punctuation
            text = self.normalize_punctuation(text)
            
            bbox = block["bbox"]
            
            # Scale bbox
            x1 = int(bbox["x1"] * scale)
            y1 = int(bbox["y1"] * scale)
            x2 = int(bbox["x2"] * scale)
            y2 = int(bbox["y2"] * scale)
            
            box_width = x2 - x1
            box_height = y2 - y1
            
            print(f"   📝 Block {idx+1}: bbox=({x1},{y1})-({x2},{y2}) size={box_width}x{box_height} text={text[:50]}...")
            
            if box_width > 10 and box_height > 10:
                font, wrapped_lines = self.fit_text_to_bbox(
                    draw, text, box_width, box_height,
                    max_font=scaled_max,
                    min_font=scaled_min
                )
                
                # วาดแต่ละบรรทัด
                current_y = y1
                for line in wrapped_lines:
                    line_bbox = draw.textbbox((0, 0), line, font=font)
                    line_height = line_bbox[3] - line_bbox[1]
                    
                    if current_y + line_height <= y2:
                        draw.text((x1, current_y), line, font=font, fill="black")
                        current_y += line_height + line_spacing
                        rendered_count += 1
            else:
                print(f"   ⚠️ Block {idx+1} skipped: box too small ({box_width}x{box_height})")
        
        print(f"   ✅ Rendered {rendered_count} text blocks")
        
        
        # Render tables
        tables = page_data.get("tables", [])
        for table in tables:
            self.draw_table(draw, table, scale, font_multiplier)
        
        return canvas
    
    def draw_table(self, draw, table: Dict, scale: float, font_multiplier: float = 1.0):
        """วาดตารางพร้อมข้อความแปล"""
        bbox = table.get("bbox", {})
        
        # Scale bbox
        x1 = int(bbox.get("x1", 0) * scale)
        y1 = int(bbox.get("y1", 0) * scale)
        x2 = int(bbox.get("x2", 0) * scale)
        y2 = int(bbox.get("y2", 0) * scale)
        
        table_width = x2 - x1
        table_height = y2 - y1
        
        num_rows = table.get("num_rows", 0)
        num_cols = table.get("num_cols", 0)
        cells = table.get("cells", [])
        
        if num_rows == 0 or num_cols == 0:
            return
        
        # คำนวณขนาด cell
        cell_width = table_width // num_cols
        cell_height = table_height // num_rows
        padding = int(3 * font_multiplier)
        
        # วาดเส้นตาราง (สีเทาอ่อน)
        line_color = (180, 180, 180)
        
        # เส้นแนวนอน
        for row in range(num_rows + 1):
            cy = y1 + (row * cell_height)
            draw.line([(x1, cy), (x2, cy)], fill=line_color, width=1)
        
        # เส้นแนวตั้ง
        for col in range(num_cols + 1):
            cx = x1 + (col * cell_width)
            draw.line([(cx, y1), (cx, y2)], fill=line_color, width=1)
        
        # วาดข้อความใน cells
        for cell in cells:
            row = cell.get("row", 0)
            col = cell.get("col", 0)
            text = cell.get("translated", cell.get("text", ""))
            
            # ✅ Cleanup LLM explanations
            text = self.cleanup_llm_explanations(text)
            
            if not text:
                continue
            
            # คำนวณตำแหน่ง cell
            cx = x1 + (col * cell_width) + padding
            cy = y1 + (row * cell_height) + padding
            available_width = cell_width - (padding * 2)
            available_height = cell_height - (padding * 2)
            
            if available_width < 10 or available_height < 10:
                continue
            
            # หา font size ที่พอดี
            max_font = int(16 * font_multiplier)
            min_font = int(8 * font_multiplier)
            
            for font_size in range(max_font, min_font - 1, -1):
                font = self.get_font(font_size)
                wrapped_lines = self.wrap_text(text, font, available_width, draw)
                
                # คำนวณความสูงรวม
                total_height = 0
                for line in wrapped_lines:
                    line_bbox = draw.textbbox((0, 0), line, font=font)
                    total_height += (line_bbox[3] - line_bbox[1]) + 2
                
                if total_height <= available_height:
                    break
            
            # วาดข้อความ
            current_y = cy
            for line in wrapped_lines:
                line_bbox = draw.textbbox((0, 0), line, font=font)
                line_height = line_bbox[3] - line_bbox[1]
                
                if current_y + line_height <= cy + available_height:
                    draw.text((cx, current_y), line, fill="black", font=font)
                    current_y += line_height + 2
    
    def render_document(self, job_id: str, doc_result: Dict[str, Any]) -> str:
        """Render เอกสารทั้งหมดและบันทึก พร้อม export หลายรูปแบบ"""
        from app.services.export_service import export_service
        
        output_dir = settings.OUTPUT_DIR / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        
        images = []
        
        for page_no in range(1, doc_result["num_pages"] + 1):
            # Support both integer and string page keys (JSON converts int to string)
            page_data = doc_result["pages"].get(page_no) or doc_result["pages"].get(str(page_no))
            
            # Skip if page_data is None
            if page_data is None:
                print(f"   ⚠️ Render: Page {page_no} not found, skipping...")
                continue
            
            canvas = self.render_page(page_data, page_no)
            
            # บันทึก PNG
            png_path = output_dir / f"translated_{page_no:03d}.png"
            canvas.save(str(png_path))
            images.append(canvas)
        
        # สร้าง PDF
        pdf_path = output_dir / "translated.pdf"
        if images:
            images[0].save(
                str(pdf_path), 
                "PDF", 
                resolution=100.0, 
                save_all=True, 
                append_images=images[1:]
            )
        
        # Close images
        for img in images:
            img.close()
        
        # ★ สร้าง export formats เพิ่มเติม
        try:
            export_service.export_to_docx(doc_result, str(output_dir / "translated.docx"))
            export_service.export_to_pptx(doc_result, str(output_dir / "translated.pptx"))
            export_service.export_to_xlsx(doc_result, str(output_dir / "translated.xlsx"))
            export_service.export_to_html(doc_result, str(output_dir / "translated.html"))
        except Exception as e:
            print(f"⚠️ Export error (non-critical): {e}")
        
        return str(pdf_path)


# Singleton instance
render_service = RenderService()
