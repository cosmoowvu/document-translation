
import os
import re
from typing import Dict, Any
from PIL import Image, ImageDraw, ImageStat
from app.services.text_processor import cleanup_llm_explanations, normalize_punctuation
from app.services.render.table_renderer import parse_html_table, draw_table, markdown_table_to_html

def render_page_overlay(page_data: Dict, page_no: int, dpi: int, font_service: Any) -> Image.Image:
    """Render single page with Overlay (Inpaint + Text)"""
    scale = dpi / 72
    width = int(page_data["width"] * scale)
    height = int(page_data["height"] * scale)
    
    print(f"   🎨 Rendering page {page_no}: {width}x{height}px (scale={scale:.2f}, DPI={dpi})")
    
    # Check for background image (Overlay Mode)
    image_path = page_data.get("image_path")
    if image_path and os.path.exists(image_path):
        print(f"      🖼️ Loading background image: {os.path.basename(image_path)}")
        try:
            canvas = Image.open(image_path).convert("RGB")
            # Resize if needed
            if canvas.size != (width, height):
                canvas = canvas.resize((width, height), Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"      ⚠️ Failed to load background image: {e}")
            canvas = Image.new('RGB', (width, height), 'white')
    else:
        canvas = Image.new('RGB', (width, height), 'white')

    draw = ImageDraw.Draw(canvas)
    
    # Pre-pass: "Inpaint" (Erase) original text areas — skip image blocks
    if image_path and os.path.exists(image_path):
        for block in page_data.get("blocks", []):
            # Skip image blocks — keep original pixels
            if block.get("is_image"):
                continue
            # [SAFETY] If block has no text (e.g. graphic that failed OCR), DO NOT ERASE IT.
            if not block.get("text", "").strip():
                continue

            bbox = block["bbox"]
            # Add padding to ensure full text erasure (5px scaled)
            padding = int(5 * scale)
            x1 = max(0, int(bbox["x1"] * scale) - padding)
            y1 = max(0, int(bbox["y1"] * scale) - padding)
            x2 = min(width, int(bbox["x2"] * scale) + padding)
            y2 = min(height, int(bbox["y2"] * scale) + padding)
            
            # [SMART INPAINT] Use median color of the area to fill
            try:
                crop = canvas.crop((x1, y1, x2, y2))
                stat = ImageStat.Stat(crop)
                median_bg = tuple(map(int, stat.median))
                draw.rectangle([x1, y1, x2, y2], fill=median_bg)
            except Exception as e:
                print(f"      ⚠️ Inpaint failed for block, using white: {e}")
                draw.rectangle([x1, y1, x2, y2], fill="white")
    
    # Font Multiplier (Smart Scaling)
    reference_width = dpi * 8.27
    font_multiplier = max(1.0, width / reference_width)
    
    scaled_max = int(36 * font_multiplier)
    scaled_min = int(12 * font_multiplier)
    
    # Render text blocks
    rendered_count = 0
    all_blocks_scaled = []
    for b in page_data["blocks"]:
        bb = b["bbox"]
        all_blocks_scaled.append({
            "x1": int(bb["x1"] * scale),
            "y1": int(bb["y1"] * scale),
            "x2": int(bb["x2"] * scale),
            "y2": int(bb["y2"] * scale),
            "label": b.get("label", "text"),
        })

    for idx, block in enumerate(page_data["blocks"]):
        # IMAGE BLOCK: skip text rendering entirely
        if block.get("is_image"):
            continue

        text = block["text"]
        
        # Cleanup
        text = cleanup_llm_explanations(text)
        text = normalize_punctuation(text)
        
        bbox = block["bbox"]
        
        x1 = int(bbox["x1"] * scale)
        y1 = int(bbox["y1"] * scale)
        x2 = int(bbox["x2"] * scale)
        y2 = int(bbox["y2"] * scale)
        
        box_height = y2 - y1

        # ── Expand right edge symmetrically ─────────────────────────────
        left_margin = x1   # distance from page left = our margin unit
        right_limit = width - left_margin  # symmetric margin on the right
        for ob in all_blocks_scaled:
            if ob["x1"] <= x1:  # only blocks to the right
                continue
            v_overlap = min(y2, ob["y2"]) - max(y1, ob["y1"])
            if v_overlap > box_height * 0.3:  # same horizontal band
                right_limit = min(right_limit, ob["x1"] - 4)
        box_width = max(x2 - x1, right_limit - x1)
        # ─────────────────────────────────────────────────────────────────

        # Convert markdown table → HTML before checking for <table>
        text = markdown_table_to_html(text)

        print(f"   📝 Block {idx+1}: bbox=({x1},{y1})-({x2},{y2}) box_width={box_width} text={text[:50]}...")

        # Check if block contains HTML table
        full_match = re.search(r'(.*?)(<table.*?>.*?</table>)(.*)', text, re.IGNORECASE | re.DOTALL)
        
        if full_match:
            print(f"      📊 Block {idx+1} contains HTML Table")
            
            pre_text = full_match.group(1).strip()
            table_full_html = full_match.group(2)
            post_text = full_match.group(3).strip()
            
            parsed_table = parse_html_table(table_full_html)
            
            if parsed_table:
                # 1. Render Pre-text (Caption)
                current_content_y = y1
                
                if pre_text:
                    caption_font_size = int(max(scaled_min, scaled_max * 0.7))
                    caption_font = font_service.get_font(caption_font_size, text=pre_text)
                    
                    wrapped_caption = font_service.wrap_text(pre_text, caption_font, box_width, draw)
                    
                    for line in wrapped_caption:
                        line_bbox = draw.textbbox((0, 0), line, font=caption_font)
                        line_height = line_bbox[3] - line_bbox[1]
                        
                        if current_content_y + line_height < y2:
                            draw.text((x1, current_content_y), line, font=caption_font, fill="black")
                            current_content_y += line_height + int(4 * font_multiplier)
                
                # 2. Render Table (in remaining space)
                remaining_height = y2 - current_content_y
                
                if remaining_height > 20: 
                    # Update bbox to point to remaining space
                    # draw_table expects UN-SCALED bbox logic usually? 
                    # Wait, draw_table in utils scales it again!
                    # Logic in original file: 
                    # parsed_table["bbox"] = { "x1": x1/scale, "y1": ... } 
                    # So we need to normalize back to original coordinates for draw_table
                    parsed_table["bbox"] = {
                        "x1": x1 / scale,
                        "y1": current_content_y / scale,
                        "x2": x2 / scale,
                        "y2": y2 / scale
                    }
                    draw_table(draw, parsed_table, scale, font_service, font_multiplier)
                else:
                    print(f"      ⚠️ Not enough space for table in Block {idx+1}")
                
                rendered_count += 1
                continue # Skip standard text rendering
        
        if box_width > 10 and box_height > 10:
            font, wrapped_lines = font_service.fit_text_to_bbox(
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
    
    # ── Paste image blocks at their original positions ───────────────────
    for idx, block in enumerate(page_data.get("blocks", [])):
        if not block.get("is_image"):
            continue
        img_path = block.get("image_path", "")
        if not img_path or not os.path.exists(img_path):
            continue
        bbox = block["bbox"]
        x1 = int(bbox["x1"] * scale)
        y1 = int(bbox["y1"] * scale)
        x2 = int(bbox["x2"] * scale)
        y2 = int(bbox["y2"] * scale)
        try:
            img_block = Image.open(img_path).convert("RGBA")
            img_block = img_block.resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
            canvas.paste(img_block, (x1, y1), img_block)
            print(f"   🖼️ Pasted image block {idx+1} at ({x1},{y1})-({x2},{y2})")
        except Exception as _ie:
            print(f"   ⚠️ Failed to paste image block {idx+1}: {_ie}")
    # ─────────────────────────────────────────────────────────────────────

    # Render tables (legacy structured tables from OCR result, if any)
    tables = page_data.get("tables", [])
    for table in tables:
        draw_table(draw, table, scale, font_service, font_multiplier)
    
    return canvas
