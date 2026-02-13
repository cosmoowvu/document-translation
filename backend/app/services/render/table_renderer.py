
import re
from typing import Dict, Any, List
from PIL import ImageDraw
from app.services.text_processor import cleanup_llm_explanations

def parse_html_table(html_text: str) -> Dict:
    """Parse HTML table string into structured dict"""
    # Cleanup: Remove newlines INSIDE tags
    html_text = re.sub(r'>\s+<', '><', html_text)
    html_text = html_text.replace('\r\n', ' ').replace('\n', ' ')
    
    # Simple regex parsing
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
            # Remove inner tags
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

def draw_table(draw: ImageDraw.ImageDraw, table: Dict, scale: float, font_service: Any, font_multiplier: float = 1.0) -> int:
    """Draw table with translated text. Return used height in pixels."""
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
    
    cell_width = table_width // num_cols
    cell_height = table_height // num_rows
    # Safety check for divide by zero if height is 0 (though unlikely with bbox)
    if cell_height <= 0: cell_height = 20
    
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
        
        max_font = int(14 * font_multiplier)
        min_font = int(8 * font_multiplier)
        
        # Simple font fitting
        font = font_service.get_font(min_font, text=text)
        
        # Try to find best fit
        for font_size in range(max_font, min_font - 1, -1):
            font = font_service.get_font(font_size, text=text)
            wrapped_lines = font_service.wrap_text(text, font, available_width, draw)
            
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
