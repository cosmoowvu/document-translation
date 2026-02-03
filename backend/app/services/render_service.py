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
        
        # Regex for table detection
        import re
        
        for para_idx, para in enumerate(paragraphs):
            para_text = para["text"]
            para_type = para["type"]
            
            # Check for HTML Table in Flow Mode (Relaxed Check)
            table_match = re.search(r'<table.*?>(.*?)</table>', para_text, re.DOTALL | re.IGNORECASE)
            
            if table_match:
                print(f"      📊 Flow Paragraph {para_idx+1} contains HTML Table")
                
                # Split content
                table_start = table_match.start()
                table_end = table_match.end()
                
                pre_text = para_text[:table_start].strip()
                table_html = para_text[table_start:table_end]
                post_text = para_text[table_end:].strip()
                
                # 1. Render Pre-text (Caption)
                if pre_text:
                     # Check Overflow
                     # (For simplicity in flow, we just write. If overflow, we should have handled it before or strict check.
                     # But splitting makes it tricky. Let's just wrap and write.)
                     wrapped_lines = self.font_service.wrap_text(pre_text, font, max_width, draw)
                     for line in wrapped_lines:
                        line_bbox = draw.textbbox((0, 0), line, font=font)
                        line_height = line_bbox[3] - line_bbox[1]
                        
                        if cursor_y + line_height > y_end:
                             print(f"   📄 Page overflow (pre-text): Creating new page")
                             images.append(canvas)
                             canvas = Image.new('RGB', (page_width, page_height), 'white')
                             draw = ImageDraw.Draw(canvas)
                             cursor_y = y_start
                        
                        draw.text((x_start, cursor_y), line, font=font, fill="black")
                        cursor_y += line_height + line_spacing
                     
                     cursor_y += paragraph_spacing

                # 2. Render Table
                parsed_table = self._parse_html_table(table_html)
                if parsed_table:
                    # Estimate height
                    table_height_estimate = (parsed_table["num_rows"] * int(30 * font_multiplier)) + 20
                    
                    if cursor_y + table_height_estimate > y_end:
                         print(f"   📄 Page overflow (table): Creating new page")
                         images.append(canvas)
                         canvas = Image.new('RGB', (page_width, page_height), 'white')
                         draw = ImageDraw.Draw(canvas)
                         cursor_y = y_start
                    
                    # Construct bbox for table (flow)
                    flow_bbox = {
                        "x1": x_start / scale,
                        "y1": cursor_y / scale,
                        "x2": x_end / scale,
                        "y2": (cursor_y + table_height_estimate) / scale 
                    }
                    parsed_table["bbox"] = flow_bbox
                    
                    # Draw
                    used_height = self._draw_table(draw, parsed_table, scale, font_multiplier)
                    cursor_y += used_height + paragraph_spacing
                
                # 3. Render Post-text
                if post_text:
                     wrapped_lines = self.font_service.wrap_text(post_text, font, max_width, draw)
                     for line in wrapped_lines:
                        line_bbox = draw.textbbox((0, 0), line, font=font)
                        line_height = line_bbox[3] - line_bbox[1]
                        
                        if cursor_y + line_height > y_end:
                             print(f"   📄 Page overflow (post-text): Creating new page")
                             images.append(canvas)
                             canvas = Image.new('RGB', (page_width, page_height), 'white')
                             draw = ImageDraw.Draw(canvas)
                             cursor_y = y_start
                        
                        draw.text((x_start, cursor_y), line, font=font, fill="black")
                        cursor_y += line_height + line_spacing

                continue

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
        
        # Regex for table
        import re

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

            # Check if block contains HTML table (Robust Regex)
            # Match: Pre-Text (Caption) + Table + Post-Text
            full_match = re.search(r'(.*?)(<table.*?>.*?</table>)(.*)', text, re.IGNORECASE | re.DOTALL)
            
            if full_match:
                print(f"      📊 Block {idx+1} contains HTML Table")
                
                pre_text = full_match.group(1).strip()
                table_full_html = full_match.group(2)
                post_text = full_match.group(3).strip()
                
                parsed_table = self._parse_html_table(table_full_html)
                
                if parsed_table:
                    # 1. Render Pre-text (Caption)
                    current_content_y = y1
                    
                    if pre_text:
                        # Use a reasonable font size for caption
                        caption_font_size = int(max(scaled_min, scaled_max * 0.7))
                        caption_font = self.font_service.get_font(caption_font_size)
                        
                        wrapped_caption = self.font_service.wrap_text(pre_text, caption_font, box_width, draw)
                        
                        for line in wrapped_caption:
                            line_bbox = draw.textbbox((0, 0), line, font=caption_font)
                            line_height = line_bbox[3] - line_bbox[1]
                            
                            if current_content_y + line_height < y2:
                                draw.text((x1, current_content_y), line, font=caption_font, fill="black")
                                current_content_y += line_height + int(4 * font_multiplier)
                    
                    # 2. Render Table (in remaining space)
                    remaining_height = y2 - current_content_y
                    
                    if remaining_height > 20: # Minimum height check
                        # Update bbox to point to remaining space
                        # _draw_table expects UN-SCALED bbox because it multiplies by scale internally
                        parsed_table["bbox"] = {
                            "x1": x1 / scale,
                            "y1": current_content_y / scale,
                            "x2": x2 / scale,
                            "y2": y2 / scale
                        }
                        self._draw_table(draw, parsed_table, scale, font_multiplier)
                    else:
                        print(f"      ⚠️ Not enough space for table in Block {idx+1}")
                    
                    rendered_count += 1
                    continue # Skip standard text rendering for this block

            
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
        
        # Render tables (legacy structured tables)
        tables = page_data.get("tables", [])
        for table in tables:
            self._draw_table(draw, table, scale, font_multiplier)
        
        return canvas
    
    def _parse_html_table(self, html_text: str) -> Dict:
        """Parse HTML table string into structured dict"""
        import re
        
        # Simple regex parsing (robust enough for LLM output)
        rows = re.findall(r'<tr.*?>(.*?)</tr>', html_text, re.DOTALL | re.IGNORECASE)
        
        if not rows:
            return None
            
        cells_data = []
        max_cols = 0
        
        for r_idx, row_html in enumerate(rows):
            # Find cells (td or th)
            cols = re.findall(r'<t[dh].*?>(.*?)</t[dh]>', row_html, re.DOTALL | re.IGNORECASE)
            max_cols = max(max_cols, len(cols))
            
            for c_idx, cell_content in enumerate(cols):
                # Remove inner tags if any (simple cleanup)
                clean_text = re.sub(r'<[^>]+>', '', cell_content).strip()
                cells_data.append({
                    "row": r_idx,
                    "col": c_idx,
                    "text": clean_text,
                    "translated": clean_text
                })
        
        return {
            "num_rows": len(rows),
            "num_cols": max_cols,
            "cells": cells_data
        }
    
    def _draw_table(self, draw, table: Dict, scale: float, font_multiplier: float = 1.0) -> int:
        """วาดตารางพร้อมข้อความแปล Return used height in pixels"""
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
            return 0
        
        # Calculate optimal row heights based on content?
        # For now, fixed uniform distribution as per original logic, 
        # but we should respect the bbox height provided.
        # However, for mixed content, we passed a bbox that goes to the bottom of the block.
        # We might want to auto-calc height if needed?
        # Let's stick to the allocated space (uniform) for now to be safe with fixed layouts.
        
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
            
            max_font = int(14 * font_multiplier) # Slightly smaller for tables
            min_font = int(8 * font_multiplier)
            
            # Simple font fitting
            font = self.font_service.get_font(min_font) # Default to min if small space
            
            # Try to find best fit
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
        
        return table_height
    
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
