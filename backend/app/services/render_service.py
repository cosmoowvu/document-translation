"""
Render Service
วาดข้อความแปลลงบน canvas ตาม bounding box
(Refactored: uses font_service and text_processor)
"""
import os
from typing import Dict, Any, List
from PIL import Image, ImageDraw

from app.config import settings
from app.services.font_service import font_service
from app.services.text_processor import (
    normalize_punctuation,
    cleanup_llm_explanations,
    normalize_ocr_text,
    is_ocr_flow_mode
)


class RenderService:
    def __init__(self):
        self.dpi = settings.DPI
        self.font_service = font_service
    
    def render_page_flow(self, page_data: Dict, page_no: int, 
                         base_font_size: int = 24,
                         margins: Dict = None) -> List[Image.Image]:
        """
        Render หน้าแบบ flow-based สำหรับ OCR images
        Return list of images (may be multiple if overflow)
        """
        # Default margins (0.5 inch = 36 points, scaled to DPI)
        scale = self.dpi / 72
        if margins is None:
            margin_pts = 36 
            margins = {
                "top": int(margin_pts * scale),
                "bottom": int(margin_pts * scale),
                "left": int(margin_pts * scale),
                "right": int(margin_pts * scale)
            }
        
        # Page dimensions
        page_width = int(page_data["width"] * scale)
        page_height = int(page_data["height"] * scale)
        
        # Calculate writing area
        x_start = margins["left"]
        x_end = page_width - margins["right"]
        y_start = margins["top"]
        y_end = page_height - margins["bottom"]
        max_width = x_end - x_start
        
        print(f"   🎨 Flow rendering page {page_no}: {page_width}x{page_height}px")
        print(f"   📐 Writing area: x={x_start}-{x_end}, y={y_start}-{y_end}, max_width={max_width}")
        
        # Get text from single block
        blocks = page_data.get("blocks", [])
        if not blocks:
            canvas = Image.new('RGB', (page_width, page_height), 'white')
            return [canvas]
        
        text = blocks[0].get("text", "")
        
        # Cleanup and normalize (delegated to text_processor)
        text = cleanup_llm_explanations(text)
        text = normalize_punctuation(text)
        
        # Parse into paragraphs (delegated to text_processor)
        paragraphs = normalize_ocr_text(text)
        print(f"   📄 Flow rendering mode: {len(paragraphs)} paragraphs")
        
        # Dynamic Font Sizing Logic
        calculated_base_size = base_font_size
        
        if len(blocks) > 1:
            # Multiple Blocks -> Use Average BBox Height
            total_h = 0
            count = 0
            for b in blocks:
                h = b["bbox"]["y2"] - b["bbox"]["y1"]
                if h > 5:
                    total_h += h
                    count += 1
            if count > 0:
                avg_h = total_h / count
                calculated_base_size = int(avg_h * 0.8 / scale)
                print(f"   📏 Dynamic Font (BBox): Avg Height={avg_h:.1f}px -> Base Size={calculated_base_size}px")
        else:
            # Single Block -> Use Readability Heuristic (70 chars per line)
            target_chars_per_line = 70
            calculated_base_size = int(max_width / (target_chars_per_line * 0.55))
            print(f"   📏 Dynamic Font (Readability): Width={max_width}px -> Target 70 chars/line -> Base Size={calculated_base_size}px")
        
        # Clamp to reasonable limits (14 - 72)
        calculated_base_size = max(14, min(72, calculated_base_size))
        
        # Font scaling for large pages
        font_multiplier = max(1.0, page_width / (self.dpi * 8.27))
        scaled_font_size = int(calculated_base_size * font_multiplier)
        font = self.font_service.get_font(scaled_font_size)
        
        print(f"   🔤 Final Font Size: {scaled_font_size}px (CalculatedBase={calculated_base_size}, Multiplier={font_multiplier:.2f})")
        
        # Spacing settings
        line_spacing = int(8 * font_multiplier)
        paragraph_spacing = int(16 * font_multiplier)
        heading_spacing = int(24 * font_multiplier)
        
        # Create first canvas
        images = []
        canvas = Image.new('RGB', (page_width, page_height), 'white')
        draw = ImageDraw.Draw(canvas)
        
        cursor_y = y_start
        
        for para_idx, para in enumerate(paragraphs):
            para_text = para["text"]
            para_type = para["type"]
            
            # Add spacing before paragraph
            if para_idx > 0:
                if para_type == "heading":
                    cursor_y += heading_spacing
                else:
                    cursor_y += paragraph_spacing
            
            # Wrap text (delegated to font_service)
            wrapped_lines = self.font_service.wrap_text(para_text, font, max_width, draw)
            
            for line in wrapped_lines:
                line_bbox = draw.textbbox((0, 0), line, font=font)
                line_height = line_bbox[3] - line_bbox[1]
                
                # Check Y overflow
                if cursor_y + line_height > y_end:
                    print(f"   📄 Page overflow at paragraph {para_idx+1}: Creating new page")
                    images.append(canvas)
                    canvas = Image.new('RGB', (page_width, page_height), 'white')
                    draw = ImageDraw.Draw(canvas)
                    cursor_y = y_start
                
                draw.text((x_start, cursor_y), line, font=font, fill="black")
                cursor_y += line_height + line_spacing
        
        images.append(canvas)
        print(f"   ✅ Flow rendered {len(paragraphs)} paragraphs into {len(images)} page(s)")
        
        return images

    def render_page(self, page_data: Dict, page_no: int) -> Image.Image:
        """Render หน้าเดียว (blocks + tables)"""
        scale = self.dpi / 72
        width = int(page_data["width"] * scale)
        height = int(page_data["height"] * scale)
        
        print(f"   🎨 Rendering page {page_no}: {width}x{height}px (scale={scale:.2f}, DPI={self.dpi})")
        
        canvas = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(canvas)
        
        # Font Multiplier (Smart Scaling)
        reference_width = self.dpi * 8.27
        font_multiplier = max(1.0, width / reference_width)
        
        scaled_max = int(36 * font_multiplier)
        scaled_min = int(12 * font_multiplier)
        
        # Render text blocks
        rendered_count = 0
        for idx, block in enumerate(page_data["blocks"]):
            text = block["text"]
            
            # Cleanup (delegated to text_processor)
            text = cleanup_llm_explanations(text)
            text = normalize_punctuation(text)
            
            bbox = block["bbox"]
            
            x1 = int(bbox["x1"] * scale)
            y1 = int(bbox["y1"] * scale)
            x2 = int(bbox["x2"] * scale)
            y2 = int(bbox["y2"] * scale)
            
            box_width = x2 - x1
            box_height = y2 - y1
            
            print(f"   📝 Block {idx+1}: bbox=({x1},{y1})-({x2},{y2}) size={box_width}x{box_height} text={text[:50]}...")
            
            if box_width > 10 and box_height > 10:
                font, wrapped_lines = self.font_service.fit_text_to_bbox(
                    draw, text, box_width, box_height,
                    max_font=scaled_max,
                    min_font=scaled_min
                )
                
                current_y = y1
                actual_line_spacing = int(font.size * 0.2)
                
                for line in wrapped_lines:
                    line_bbox = draw.textbbox((0, 0), line, font=font)
                    line_height = line_bbox[3] - line_bbox[1]
                    
                    draw.text((x1, current_y), line, font=font, fill="black")
                    current_y += line_height + actual_line_spacing
                    rendered_count += 1
            else:
                print(f"   ⚠️ Block {idx+1} skipped: box too small ({box_width}x{box_height})")
        
        print(f"   ✅ Rendered {rendered_count} text blocks")
        
        # Render tables
        tables = page_data.get("tables", [])
        for table in tables:
            self._draw_table(draw, table, scale, font_multiplier)
        
        return canvas
    
    def _draw_table(self, draw, table: Dict, scale: float, font_multiplier: float = 1.0):
        """วาดตารางพร้อมข้อความแปล"""
        bbox = table.get("bbox", {})
        
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
        
        cell_width = table_width // num_cols
        cell_height = table_height // num_rows
        padding = int(3 * font_multiplier)
        
        line_color = (180, 180, 180)
        
        # Draw grid lines
        for row in range(num_rows + 1):
            cy = y1 + (row * cell_height)
            draw.line([(x1, cy), (x2, cy)], fill=line_color, width=1)
        
        for col in range(num_cols + 1):
            cx = x1 + (col * cell_width)
            draw.line([(cx, y1), (cx, y2)], fill=line_color, width=1)
        
        # Draw cell text
        for cell in cells:
            row = cell.get("row", 0)
            col = cell.get("col", 0)
            text = cell.get("translated", cell.get("text", ""))
            
            text = cleanup_llm_explanations(text)
            
            if not text:
                continue
            
            cx = x1 + (col * cell_width) + padding
            cy = y1 + (row * cell_height) + padding
            available_width = cell_width - (padding * 2)
            available_height = cell_height - (padding * 2)
            
            if available_width < 10 or available_height < 10:
                continue
            
            max_font = int(16 * font_multiplier)
            min_font = int(8 * font_multiplier)
            
            for font_size in range(max_font, min_font - 1, -1):
                font = self.font_service.get_font(font_size)
                wrapped_lines = self.font_service.wrap_text(text, font, available_width, draw)
                
                total_height = 0
                for line in wrapped_lines:
                    line_bbox = draw.textbbox((0, 0), line, font=font)
                    total_height += (line_bbox[3] - line_bbox[1]) + 2
                
                if total_height <= available_height:
                    break
            
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
            page_data = doc_result["pages"].get(page_no) or doc_result["pages"].get(str(page_no))
            
            if page_data is None:
                print(f"   ⚠️ Render: Page {page_no} not found, skipping...")
                continue
            
            # Check if OCR flow mode (delegated to text_processor)
            if is_ocr_flow_mode(page_data):
                print(f"   📄 Page {page_no}: Using flow rendering mode")
                page_images = self.render_page_flow(page_data, page_no)
                
                for flow_idx, canvas in enumerate(page_images):
                    if len(page_images) == 1:
                        png_path = output_dir / f"translated_{page_no:03d}.png"
                    else:
                        png_path = output_dir / f"translated_{page_no:03d}_{flow_idx+1:02d}.png"
                    canvas.save(str(png_path))
                    images.append(canvas)
            else:
                canvas = self.render_page(page_data, page_no)
                
                png_path = output_dir / f"translated_{page_no:03d}.png"
                canvas.save(str(png_path))
                images.append(canvas)
        
        # Create PDF
        pdf_path = output_dir / "translated.pdf"
        if images:
            images[0].save(
                str(pdf_path), 
                "PDF", 
                resolution=100.0, 
                save_all=True, 
                append_images=images[1:]
            )
        
        for img in images:
            img.close()
        
        # Generate export formats
        try:
            export_service.export_to_docx(doc_result, str(output_dir / "translated.docx"))
        except Exception as e:
            print(f"⚠️ Export error (non-critical): {e}")
        
        return str(pdf_path)


# Singleton instance
render_service = RenderService()
