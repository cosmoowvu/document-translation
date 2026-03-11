
import re
from typing import Dict, Any, List
from PIL import ImageDraw
from app.services.text_processor import cleanup_llm_explanations


def _normalize_table_html(html: str) -> str:
    """Fix common malformed <td> patterns from Typhoon OCR."""
    def _fix_tag(m):
        tag  = m.group(1)
        rest = m.group(2)
        if re.match(r'^[\w-]+[\s=>]', rest):
            return f"<{tag} {rest}"
        return f"<{tag}>{rest}"

    html = re.sub(r'<(t[dh])\s+([^>]*)', _fix_tag, html)
    html = re.sub(r'<(tr)\s+([^>]*?)(?=<t[dh])', lambda m: '<tr>', html)
    return html


def markdown_table_to_html(text: str) -> str:
    """
    Convert markdown pipe-table to HTML table.
    Input:  | Col1 | Col2 |\\n|---|---|\\n| A | B |
    Output: <table><tr><th>Col1</th><th>Col2</th></tr>...
    Only converts when a clear pipe-table pattern is detected.
    Returns original text if not a markdown table.
    """
    lines = [l.strip() for l in text.strip().splitlines()]
    # Need at least 3 lines: header, separator, data
    if len(lines) < 2:
        return text

    # Check if it looks like a markdown table (lines with | )
    pipe_lines = [l for l in lines if l.startswith('|') and l.endswith('|')]
    if len(pipe_lines) < 2:
        return text

    html_rows = []
    is_first = True
    for line in lines:
        if not line.startswith('|'):
            continue
        # Skip separator line (|----|-----|)
        if re.match(r'^[\|\-\:\s]+$', line):
            is_first = False
            continue
        # Parse cells
        cells = [c.strip() for c in line.strip('|').split('|')]
        tag = 'th' if is_first else 'td'
        row_html = ''.join(f"<{tag}>{c}</{tag}>" for c in cells)
        html_rows.append(f"<tr>{row_html}</tr>")
        is_first = False

    if not html_rows:
        return text

    return f"<table>{''.join(html_rows)}</table>"


def parse_html_table(html_text: str) -> Dict:
    """Parse HTML table string into structured dict"""
    # Step 0: Normalize malformed tags first
    html_text = _normalize_table_html(html_text)

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
        cols = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL | re.IGNORECASE)
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
        "cells": cells_data,
        "bbox": {}
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
    
    # First pass: determine uniform font size for the entire table
    # Base it on the dimension of the table, not hardcoded small values
    # cell_height is the height of a single row. A good max font size is roughly half the cell height, capped.
    dynamic_max_font = min(int(cell_height * 0.6), int(40 * font_multiplier)) 
    dynamic_max_font = max(dynamic_max_font, int(16 * font_multiplier)) # Ensure at least 16
    
    max_font_allowed = dynamic_max_font
    min_font_allowed = int(10 * font_multiplier)
    
    table_font_size = max_font_allowed
    
    valid_cells = []
    
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
            
        valid_cells.append({
            "text": text,
            "cx": cx,
            "cy": cy,
            "available_width": available_width,
            "available_height": available_height
        })
        
        # Find best font for THIS cell
        best_size = min_font_allowed
        for font_size in range(max_font_allowed, min_font_allowed - 1, -1):
            font = font_service.get_font(font_size, text=text)
            wrapped_lines = font_service.wrap_text(text, font, available_width, draw)
            
            total_height = 0
            for line in wrapped_lines:
                line_bbox = draw.textbbox((0, 0), line, font=font)
                total_height += (line_bbox[3] - line_bbox[1]) + 2
                
            if total_height <= available_height:
                best_size = font_size
                break
                
        table_font_size = min(table_font_size, best_size)

    # Second pass: Draw all cells with the uniform font size
    font = font_service.get_font(table_font_size)
    
    for cell in valid_cells:
        text = cell["text"]
        cx = cell["cx"]
        cy = cell["cy"]
        available_width = cell["available_width"]
        available_height = cell["available_height"]
        
        # Re-wrap text with the chosen uniform font
        # If font_service.get_font requires text to detect script for fallback fonts:
        cell_font = font_service.get_font(table_font_size, text=text)
        wrapped_lines = font_service.wrap_text(text, cell_font, available_width, draw)
        
        current_y = cy
        for line in wrapped_lines:
            line_bbox = draw.textbbox((0, 0), line, font=cell_font)
            line_height = line_bbox[3] - line_bbox[1]
            
            # Draw regardless of height to guarantee it renders, we already constrained the baseline font size
            # But cap at available_height to strictly prevent visible vertical overflow over cell boundaries
            if current_y + line_height <= cy + available_height + (line_height * 0.5): # allow slight visual overlap
                draw.text((cx, current_y), line, fill="black", font=cell_font)
                current_y += line_height + 2
    
    return table_height
