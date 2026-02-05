"""
HTML Generator Service
Generates HTML representation from Page Data (Blocks + BBox)
Used for creating high-fidelity layouts from OCR results
"""
import base64
import os
from typing import Dict, List

class HtmlGeneratorService:
    def generate_html(self, page_data: Dict, image_path: str = None) -> str:
        """
        Generate HTML from page data
        """
        width = page_data.get("width", 800)
        height = page_data.get("height", 600)
        blocks = page_data.get("blocks", [])
        
        # 1. Prepare Background Image (Base64)
        bg_style = ""
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as img_file:
                b64_str = base64.b64encode(img_file.read()).decode('utf-8')
                bg_style = f"background-image: url('data:image/jpeg;base64,{b64_str}');"
        
        # 2. Build HTML
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            margin: 0;
            padding: 0;
            background-color: #333;
            display: flex;
            justify_content: center;
        }}
        .page {{
            position: relative;
            width: {width}px;
            height: {height}px;
            background-color: white;
            background-size: contain;
            background-repeat: no-repeat;
            {bg_style}
            box-shadow: 0 0 20px rgba(0,0,0,0.5);
        }}
        .block {{
            position: absolute;
            background-color: rgba(255, 255, 255, 0.9); /* Slight transparency to blend but hide original */
            border: 0px solid red; /* Debug */
            display: flex;
            align-items: center; /* Vertical Center */
            justify-content: flex-start; /* Left align usually better for text */
            overflow: hidden;
            font-family: 'Sarabun', 'Noto Sans Thai', sans-serif;
            line-height: 1.2;
            padding: 2px;
            box-sizing: border-box;
            white-space: pre-wrap; /* Preserve newlines */
            word-break: break-word;
        }}
    </style>
    <!-- Google Fonts for Thai -->
    <link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;600&display=swap" rel="stylesheet">
    <script>
        // Auto-fit function
        function fitText(el) {{
            let maxFont = 100;
            let minFont = 10;
            let currentFont = maxFont;
            
            // Binary search or iterative reduction
            while (currentFont >= minFont) {{
                el.style.fontSize = currentFont + "px";
                if (el.scrollHeight <= el.offsetHeight && el.scrollWidth <= el.offsetWidth) {{
                    return; // Fits!
                }}
                currentFont -= 2;
            }}
            el.style.fontSize = minFont + "px"; // Fallback
        }}

        window.onload = function() {{
            const blocks = document.querySelectorAll('.block');
            blocks.forEach(block => fitText(block));
        }};
    </script>
</head>
<body>
    <div class="page">
"""
        
        # 3. Add Blocks
        for block in blocks:
            bbox = block["bbox"]
            text = block.get("text", "")
            if not text:
                continue
                
            x1 = bbox["x1"]
            y1 = bbox["y1"]
            w = bbox["x2"] - bbox["x1"]
            h = bbox["y2"] - bbox["y1"]
            
            # Escape HTML
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            
            html_content += f"""
        <div class="block" style="left: {x1}px; top: {y1}px; width: {w}px; height: {h}px;">
            {text}
        </div>"""
            
        html_content += """
    </div>
</body>
</html>
"""
        return html_content

html_generator = HtmlGeneratorService()
