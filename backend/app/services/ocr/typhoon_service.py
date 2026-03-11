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


    def process_image_direct(self, image_path: str, source_lang: str = "tha_Thai", is_table: bool = False) -> str:
        """
        Direct VLM API call to Typhoon with strict OCR prompt.
        Prevents hallucination by instructing the model to read exactly what it sees.
        Returns extracted text string.
        """
        import requests
        import base64

        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Determine image mime type
        ext = os.path.splitext(image_path)[1].lower()
        mime_type = "image/png" if ext == ".png" else "image/jpeg"

        # Map language code to human-readable name + script hint
        lang_hints = {
            "tha_Thai": ("Thai", "Thai script (เช่น ก ข ค ง)"),
            "th":        ("Thai", "Thai script (เช่น ก ข ค ง)"),
            "jpn_Jpan":  ("Japanese", "Japanese script (Kanji/Hiragana/Katakana) — STRICTLY NO Romaji or Latin alphabets for Japanese text!"),
            "ja":        ("Japanese", "Japanese script (Kanji/Hiragana/Katakana) — STRICTLY NO Romaji or Latin alphabets for Japanese text!"),
            "zho_Hans":  ("Simplified Chinese", "Simplified Chinese characters (简体字)"),
            "zho_Hant":  ("Traditional Chinese", "Traditional Chinese characters (繁體字)"),
            "zh":        ("Chinese", "Chinese characters (汉字/漢字)"),
            "zh-cn":     ("Simplified Chinese", "Simplified Chinese characters (简体字)"),
            "kor_Hang":  ("Korean", "Korean Hangul script (한글) — carefully distinguish similar characters: 인/임, 은/큰"),
            "ko":        ("Korean", "Korean Hangul script (한글) — carefully distinguish similar characters: 인/임, 은/큰"),
            "eng_Latn":  ("English", "Latin script"),
        }
        lang_name, script_hint = lang_hints.get(source_lang, ("the document's language", "the characters as they appear"))
        lang_instruction = (
            f"This image contains {lang_name} text ({script_hint}). "
            "Pay close attention to characters that may look visually similar and transcribe each one accurately. "
        )

        # Build prompt based on block type
        if is_table:
            user_prompt = (
                f"{lang_instruction}"
                "Read all text in this image exactly as it appears. "
                "Output the content as a markdown table. "
                "Do not add, remove, or change any text. "
                "If you cannot read a cell clearly, use '?' as placeholder."
            )
        else:
            user_prompt = (
                f"{lang_instruction}"
                "Read all text in this image exactly as it appears, character by character. "
                "Output ONLY the text you see. "
                "Do NOT autocomplete, guess, or add any text that is not visible. "
                "Do NOT correct spelling or grammar. "
                "If the image contains no text, output an empty string."
            )


        payload = {
            "model": "typhoon-ocr",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict OCR engine. "
                        "Your only job is to transcribe text from images exactly as it appears. "
                        "Never autocomplete, hallucinate, or infer text that is not clearly visible. "
                        "Output only the transcribed text with no commentary."
                    )
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_data}"
                            }
                        },
                        {
                            "type": "text",
                            "text": user_prompt
                        }
                    ]
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.0,  # Zero temperature = deterministic, no creativity
        }

        try:
            resp = requests.post(
                "https://api.opentyphoon.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=120
            )

            if resp.status_code == 200:
                result = resp.json()
                text = result["choices"][0]["message"]["content"].strip()
                return text
            else:
                print(f"   ⚠️ Direct VLM API Error: {resp.status_code} - {resp.text[:200]}")
                return ""

        except Exception as e:
            print(f"   ⚠️ Direct VLM API Exception: {e}")
            return ""


    def process_document(self, file_path: str, source_lang: str = "tha_Thai", job_id: str = None, job_status: Dict = None) -> Dict[str, Any]:
        """
        Process document using Typhoon OCR Cloud API
        """
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
                    # Check cancellation
                    if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
                        print(f"      ⛔ Job {job_id} cancelled during PDF conversion")
                        raise Exception("Job cancelled")
                        
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
                # Check cancellation
                if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
                    print(f"      ⛔ Job {job_id} cancelled during Typhoon OCR loop")
                    raise Exception("Job cancelled")

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
