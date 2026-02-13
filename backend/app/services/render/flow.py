
import re
from typing import Dict, List, Any
from PIL import Image, ImageDraw
from app.services.text_processor import (
    normalize_punctuation,
    cleanup_llm_explanations,
    normalize_ocr_text
)
from app.services.render.table_renderer import parse_html_table, draw_table

def render_page_flow(page_data: Dict, page_no: int, dpi: int, font_service: Any, 
                     base_font_size: int = 24, margins: Dict = None) -> List[Image.Image]:
    """
    Render page flow-based for OCR images
    Return list of images (may be multiple if overflow)
    """
    # Default margins
    scale = dpi / 72
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
    
    # Get text from blocks
    blocks = page_data.get("blocks", [])
    if not blocks:
        canvas = Image.new('RGB', (page_width, page_height), 'white')
        return [canvas]
    
    # Concatenate all text blocks
    full_text_parts = []
    for b in blocks:
        b_text = b.get("text", "").strip()
        if b_text:
            full_text_parts.append(b_text)
    
    text = "\n\n".join(full_text_parts)
    
    # Cleanup and normalize
    text = cleanup_llm_explanations(text)
    text = normalize_punctuation(text)
    
    # Parse into paragraphs
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
        # Single Block -> Use Readability Heuristic
        target_chars_per_line = 70
        calculated_base_size = int(max_width / (target_chars_per_line * 0.55))
        print(f"   📏 Dynamic Font (Readability): Width={max_width}px -> Target 70 chars/line -> Base Size={calculated_base_size}px")
    
    # Clamp to reasonable limits
    calculated_base_size = max(14, min(72, calculated_base_size))
    
    # Font scaling for large pages
    font_multiplier = max(1.0, page_width / (dpi * 8.27))
    scaled_font_size = int(calculated_base_size * font_multiplier)
    
    # Default font
    font = font_service.get_font(scaled_font_size, text=text)
    
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
        
        # Check for HTML Table in Flow Mode
        table_match = re.search(r'<table.*?>(.*?)</table>', para_text, re.DOTALL | re.IGNORECASE)
        
        if table_match:
            print(f"      📊 Flow Paragraph {para_idx+1} contains HTML Table")
            
            # Split content
            table_start = table_match.start()
            table_end = table_match.end()
            
            pre_text = para_text[:table_start].strip()
            table_html = para_text[table_start:table_end]
            post_text = para_text[table_end:].strip()
            
            # 1. Render Pre-text
            if pre_text:
                 wrapped_lines = font_service.wrap_text(pre_text, font, max_width, draw)
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
            parsed_table = parse_html_table(table_html)
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
                used_height = draw_table(draw, parsed_table, scale, font_service, font_multiplier)
                cursor_y += used_height + paragraph_spacing
            
            # 3. Render Post-text
            if post_text:
                 wrapped_lines = font_service.wrap_text(post_text, font, max_width, draw)
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
        
        # Wrap text
        font = font_service.get_font(scaled_font_size, text=para_text)
        wrapped_lines = font_service.wrap_text(para_text, font, max_width, draw)
        
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
            
            # SAFETY
            if len(images) > 20: 
                print(f"   ⚠️ Emergency Break: Paragraph {para_idx+1} generated > 20 pages. Stopping.")
                break
    
    images.append(canvas)
    print(f"   ✅ Flow rendered {len(paragraphs)} paragraphs into {len(images)} page(s)")
    
    return images
