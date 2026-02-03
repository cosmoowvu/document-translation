"""
Typhoon OCR Service
Uses Typhoon OCR Cloud API (SCB10X) via typhoon-ocr package
"""
from typing import Dict, Any
import os


class TyphoonOCRService:
    """Typhoon OCR via Cloud API (SCB10X) using typhoon-ocr package"""
    
    def __init__(self):
        self.api_key = os.getenv("TYPHOON_OCR_API_KEY")
        if not self.api_key or self.api_key == "your_api_key_here":
            raise ValueError(
                "TYPHOON_OCR_API_KEY not properly set in .env file. "
                "Get your API key from https://playground.opentyphoon.ai/api-key"
            )
        
        # Set API key for typhoon-ocr package
        os.environ["TYPHOON_OCR_API_KEY"] = self.api_key
    
    
    def process_document(self, file_path: str, source_lang: str = "tha_Thai") -> Dict[str, Any]:
        """Process document using Typhoon OCR Cloud API"""
        from typhoon_ocr import ocr_document
        from PIL import Image as PILImage
        import fitz  # PyMuPDF
        import tempfile
        import re
        
        print(f"🌪️ Using Typhoon OCR (Cloud API)")
        
        # Determine file type and page count
        file_ext = os.path.splitext(file_path)[1].lower()
        is_pdf = file_ext == '.pdf'
        pages_to_process = []  # List of (page_num, image_path, width, height)
        
        if is_pdf:
            print(f"   📄 Converting PDF pages to images (Bypassing Poppler dependency)...")
            try:
                pdf_doc = fitz.open(file_path)
                num_pages = len(pdf_doc)
                
                for i in range(num_pages):
                    page = pdf_doc[i]
                    # Render page to image (300 DPI for good OCR)
                    pix = page.get_pixmap(dpi=300)
                    
                    # Save to temp file
                    temp_fd, temp_path = tempfile.mkstemp(suffix='.png')
                    os.close(temp_fd)
                    pix.save(temp_path)
                    
                    pages_to_process.append({
                        "page_num": i + 1,
                        "path": temp_path,
                        "width": page.rect.width,   # Original PDF points
                        "height": page.rect.height, # Original PDF points
                        "is_temp": True
                    })
                
                pdf_doc.close()
                
            except Exception as e:
                print(f"   ❌ PDF Conversion failed: {e}")
                raise
        else:
            # For images, get actual image dimensions
            num_pages = 1
            with PILImage.open(file_path) as img:
                dpi = img.info.get('dpi', (72, 72))
                if isinstance(dpi, tuple): dpi = dpi[0]
                
                page_width = (img.width / dpi) * 72
                page_height = (img.height / dpi) * 72
                
                print(f"   📐 Image dimensions: {img.width}x{img.height}px @ {dpi} DPI → {float(page_width):.1f}x{float(page_height):.1f} points")
                
                pages_to_process.append({
                    "page_num": 1,
                    "path": file_path,
                    "width": page_width,
                    "height": page_height,
                    "is_temp": False
                })
        
        print(f"   📄 Processing {num_pages} page(s)...")
        
        # Process each page
        pages = {}
        processed_count = 0
        
        try:
            for item in pages_to_process:
                page_no = item["page_num"]
                current_path = item["path"]
                
                print(f"   🔍 Page {page_no}/{num_pages}...")
                
                try:
                    # Call Typhoon OCR API with IMAGE path (works without Poppler)
                    markdown_text = ocr_document(
                        pdf_or_image_path=current_path,
                        page_num=1 # Always 1 because we are sending single page images
                    )
                    
                    # 🧹 Remove <figure> tags
                    if markdown_text:
                        markdown_text = re.sub(r'<figure>.*?</figure>', '', markdown_text, flags=re.DOTALL).strip()
                    
                    print(f"   ✅ Page {page_no}: Extracted {len(markdown_text)} characters")
                    
                    margin_points = 10 
                    blocks = [{
                        "text": markdown_text,
                        "bbox": {
                            "x1": margin_points,
                            "y1": margin_points,
                            "x2": item["width"] - margin_points,
                            "y2": item["height"] - margin_points
                        },
                        "label": "text"
                    }] if markdown_text else []
                    
                    pages[page_no] = {
                        "width": item["width"],
                        "height": item["height"],
                        "blocks": blocks,
                        "tables": []
                    }
                    processed_count += 1
                    
                except Exception as e:
                    print(f"   ❌ Page {page_no} failed: {e}")
                    raise
                    
        finally:
            # Cleanup temp files
            for item in pages_to_process:
                if item.get("is_temp") and os.path.exists(item["path"]):
                    try:
                        os.unlink(item["path"])
                    except:
                        pass
            if processed_count > 0:
                print(f"   🧹 Cleaned up temporary page images")
        
        return {
            "num_pages": num_pages,
            "pages": pages,
            "ocr_engine": "typhoon-api"
        }
