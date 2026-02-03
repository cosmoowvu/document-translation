"""
Hybrid OCR Service
Combines Docling for Layout Detection + Typhoon for Text Recognition
Result: High precision layout + High quality Thai text
"""
from typing import Dict, Any
import os


class HybridOCRService:
    """
    Hybrid OCR:
    1. Use Docling for Layout Detection (BBoxes)
    2. Use Typhoon OCR for Text Recognition (Cropped Images)
    Result: High precision layout + High quality Thai text
    """
    
    def __init__(self):
        from .docling_service import DoclingOCRService
        self.docling = DoclingOCRService()
        self.api_key = os.getenv("TYPHOON_OCR_API_KEY")
        if not self.api_key:
             print("⚠️ TYPHOON_OCR_API_KEY not set, Hybrid mode might fail for text recognition")
    
    def process_document(self, file_path: str, source_lang: str = "tha_Thai") -> Dict[str, Any]:
        """
        Process document using Hybrid approach
        Workflow: PDF -> Images -> Docling Detection (on images) -> Typhoon Refinement (on images)
        This ensures perfect coordinate alignment.
        """
        import fitz # PyMuPDF
        import concurrent.futures
        from typhoon_ocr import ocr_document
        import tempfile
        import threading
        from PIL import Image as PILImage
        
        print(f"🚀 Starting Hybrid OCR (Docling Layout + Typhoon Text) for {os.path.basename(file_path)}")
        
        # 1. Prepare Images
        # logic: if PDF -> convert all pages to temp images
        #        if Image -> use as is
        
        temp_pages = [] # List of {"path": str, "page_no": int, "is_temp": bool}
        is_pdf = file_path.lower().endswith('.pdf')
        
        if is_pdf:
            print(f"   📄 Converting PDF to images for consistent detection...")
            try:
                doc = fitz.open(file_path)
                for i in range(len(doc)):
                    page = doc[i]
                    # Render at high DPI (300) for best OCR/Detection
                    pix = page.get_pixmap(dpi=300)
                    
                    fd, temp_path = tempfile.mkstemp(suffix='.png')
                    os.close(fd)
                    pix.save(temp_path)
                    
                    temp_pages.append({
                        "path": temp_path,
                        "page_no": i + 1,
                        "is_temp": True
                    })
                doc.close()
            except Exception as e:
                print(f"   ❌ PDF Conversion failed: {e}")
                raise
        else:
            # Single image
            temp_pages.append({
                "path": file_path,
                "page_no": 1,
                "is_temp": False
            })

        # 2. Run Docling on Images
        print(f"   1️⃣  Detecting Layout with Docling (on {len(temp_pages)} images)...")
        combined_result = {
            "num_pages": len(temp_pages),
            "pages": {},
            "ocr_engine": "hybrid (docling+typhoon)"
        }
        
        # We process detection sequentially to avoid OOM with Docling models
        for p in temp_pages:
            try:
                # Run Docling on the image file
                # Docling thinks it's a 1-page document
                page_layout = self.docling.process_document(p["path"], source_lang)
                
                # Extract page 1 data (since input was single image)
                if 1 in page_layout["pages"]:
                    p_data = page_layout["pages"][1]
                    
                    # Store mapping to real page number
                    combined_result["pages"][p["page_no"]] = p_data
                else:
                    print(f"      ⚠️ No data found for page {p['page_no']}")
                    combined_result["pages"][p["page_no"]] = {"blocks": [], "tables": []}
                    
            except Exception as e:
                print(f"      ⚠️ Detection failed for page {p['page_no']}: {e}")
                combined_result["pages"][p["page_no"]] = {"blocks": [], "tables": []}

        # 3. Typhoon Refinement (using the SAME images)
        print(f"   2️⃣  Refining text with Typhoon (Parallel)...")
        
        total_blocks = 0
        refined_blocks = 0
        image_lock = threading.Lock()
        tasks = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            for p in temp_pages:
                page_no = p["page_no"]
                page_data = combined_result["pages"].get(page_no, {})
                blocks = page_data.get("blocks", [])
                
                if not blocks:
                    continue
                
                # Load the EXACT image used for detection
                try:
                    pil_img = PILImage.open(p["path"])
                except Exception as e:
                    print(f"      ⚠️ Could not load image {p['path']}: {e}")
                    continue

                # Calculate Scale
                # Since we ran Docling ON THIS IMAGE, the coordinates should be 1:1 match
                # with the image dimensions (pixels).
                # Docling usually returns coords in pixels for images.
                # However, let's verify against reported width/height
                
                info_width = page_data.get("width", 1)
                info_height = page_data.get("height", 1)
                
                scale_x = pil_img.width / info_width if info_width > 0 else 1
                scale_y = pil_img.height / info_height if info_height > 0 else 1
                
                # If scale is very close to 1.0 (e.g. 0.99-1.01), treat as 1
                if 0.99 < scale_x < 1.01: scale_x = 1.0
                if 0.99 < scale_y < 1.01: scale_y = 1.0

                print(f"      📏 Page {page_no} Scale: {scale_x:.2f}x, {scale_y:.2f}x (Image: {pil_img.width}x{pil_img.height})")
                
                for i, block in enumerate(blocks):
                    total_blocks += 1
                    tasks.append(executor.submit(
                        self._refine_block_text, 
                        block, 
                        pil_img, 
                        (scale_x, scale_y), 
                        image_lock
                    ))
            
            # Wait for completion
            for future in concurrent.futures.as_completed(tasks):
                try:
                    if future.result():
                        refined_blocks += 1
                except Exception as e:
                    print(f"      ⚠️ Block refinement failed: {e}")

        # 4. Cleanup Temp Images
        print(f"   🧹 Cleaning up temp images...")
        for p in temp_pages:
            if p["is_temp"] and os.path.exists(p["path"]):
                try:
                    os.unlink(p["path"])
                except:
                    pass

        print(f"   ✅ Hybrid OCR Complete: Refined {refined_blocks}/{total_blocks} blocks")
        return combined_result

    def _refine_block_text(self, block, full_page_img, scale_factor, image_lock):
        """Refine text of a specific block using Typhoon"""
        from typhoon_ocr import ocr_document
        import tempfile
        import re
        
        # Unpack scale
        if isinstance(scale_factor, tuple):
            scale_x, scale_y = scale_factor
        else:
            scale_x = scale_y = scale_factor

        bbox = block["bbox"]
        x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
        
        # Add small padding (relative to scale)
        padding = 25 # Increased padding to avoid cutting vowels/tails
        x1 = max(0, x1 * scale_x - padding)
        y1 = max(0, y1 * scale_y - padding)
        x2 = min(full_page_img.width, x2 * scale_x + padding)
        y2 = min(full_page_img.height, y2 * scale_y + padding)
        
        if (x2 - x1) < 10 or (y2 - y1) < 10:
            return False
            
        # Crop safely using lock
        try:
            with image_lock:
                crop_img = full_page_img.crop((x1, y1, x2, y2))
                crop_img.load() # Force load data here to avoid lazy evaluation issues later
        except Exception as e:
            print(f"      ⚠️ Failed to crop image: {e}")
            return False
        
        # Save to temp
        temp_fd, temp_path = tempfile.mkstemp(suffix='.jpg')
        os.close(temp_fd) # Close file descriptor immediately
        
        # Use JPEG for maximum compatibility
        try:
            crop_img = crop_img.convert('RGB') # Ensure RGB for JPEG
            crop_img.save(temp_path, format='JPEG', quality=95)
        except Exception as e:
            print(f"      ⚠️ Failed to save crop image: {e}")
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            return False
        
        try:
            # Call Typhoon
            # We use page_num=1 because it's a single image
            text = ocr_document(temp_path, page_num=1)
            
            if text and len(text.strip()) > 0:
                # Clean up text
                text = text.strip()
                
                # Remove markdown artifacts if any
                text = text.replace('**', '').replace('##', '')
                
                # Remove XML-like tags often hallucinations by Typhoon
                text = re.sub(r'<page_number>.*?</page_number>', '', text, flags=re.IGNORECASE)
                text = re.sub(r'<pagination>.*?</pagination>', '', text, flags=re.IGNORECASE)
                text = re.sub(r'<[^>]+>', '', text) # Remove any other XML tags
                
                text = text.strip()
                
                if not text:
                    # If text is empty after cleanup (e.g. it was just a page number), keep original
                    return False

                # Update block text
                block["text"] = text
                return True
                
        except Exception as e:
            print(f"      ⚠️ Refinement error for block {bbox}: {e}")
            return False
        finally:
            # Robust cleanup
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
        
        return False
