"""
Hybrid OCR Service
Combines EasyOCR for Layout/BBox Detection + Typhoon for Text Recognition
Result: Thai-compatible layout detection + High quality Thai text
"""
from typing import Dict, Any, List, Tuple
import os


class HybridOCRService:
    """
    Hybrid OCR:
    1. Use EasyOCR for Layout Detection (BBoxes) - supports Thai
    2. Use Typhoon OCR for Text Recognition (Cropped Images) - high accuracy
    Result: Thai-compatible layout detection + High quality Thai text
    """
    
    def __init__(self):
        import easyocr
        # Initialize EasyOCR with Thai and English
        print("🔧 Initializing EasyOCR reader (Thai + English)...")
        self.reader = easyocr.Reader(['th', 'en'], gpu=True)
        
        self.api_key = os.getenv("TYPHOON_OCR_API_KEY")
        if not self.api_key:
            print("⚠️ TYPHOON_OCR_API_KEY not set, Hybrid mode might fail for text recognition")
    
    def process_document(self, file_path: str, source_lang: str = "tha_Thai") -> Dict[str, Any]:
        """
        Process document using Hybrid approach
        Workflow: 
        1. Image/PDF -> EasyOCR Detection (get BBoxes)
        2. Crop each BBox -> Typhoon OCR (get accurate text)
        """
        import fitz  # PyMuPDF
        import concurrent.futures
        import tempfile
        import threading
        from PIL import Image as PILImage
        
        print(f"🚀 Starting Hybrid OCR (EasyOCR BBox + Typhoon Text) for {os.path.basename(file_path)}")
        
        # 1. Prepare Images
        temp_pages = []  # List of {"path": str, "page_no": int, "is_temp": bool}
        is_pdf = file_path.lower().endswith('.pdf')
        
        if is_pdf:
            print(f"   📄 Converting PDF to images...")
            try:
                doc = fitz.open(file_path)
                for i in range(len(doc)):
                    page = doc[i]
                    # Render at high DPI (300) for best OCR
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

        # 2. Run EasyOCR for BBox Detection
        print(f"   1️⃣  Detecting Layout with EasyOCR (on {len(temp_pages)} images)...")
        combined_result = {
            "num_pages": len(temp_pages),
            "pages": {},
            "ocr_engine": "hybrid (easyocr+typhoon)"
        }
        
        for p in temp_pages:
            try:
                # Load image to get dimensions
                pil_img = PILImage.open(p["path"])
                img_width, img_height = pil_img.size
                
                # Run EasyOCR - get bounding boxes
                # detail=1 returns list of (bbox, text, confidence)
                results = self.reader.readtext(p["path"], detail=1, paragraph=False)
                
                # Convert EasyOCR format to our block format
                blocks = []
                for idx, (bbox_points, text, confidence) in enumerate(results):
                    # EasyOCR returns 4 corner points: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    # Convert to x1,y1,x2,y2 format
                    x_coords = [pt[0] for pt in bbox_points]
                    y_coords = [pt[1] for pt in bbox_points]
                    
                    x1 = min(x_coords)
                    y1 = min(y_coords)
                    x2 = max(x_coords)
                    y2 = max(y_coords)
                    
                    block = {
                        "id": f"block_{p['page_no']}_{idx}",
                        "type": "text",
                        "text": text,  # EasyOCR text (will be refined by Typhoon)
                        "bbox": {
                            "x1": x1,
                            "y1": y1,
                            "x2": x2,
                            "y2": y2
                        },
                        "confidence": confidence
                    }
                    blocks.append(block)
                
                print(f"      📦 Page {p['page_no']}: Found {len(blocks)} text blocks")
                
                combined_result["pages"][p["page_no"]] = {
                    "blocks": blocks,
                    "tables": [],
                    "width": img_width,
                    "height": img_height
                }
                
            except Exception as e:
                print(f"      ⚠️ Detection failed for page {p['page_no']}: {e}")
                combined_result["pages"][p["page_no"]] = {"blocks": [], "tables": []}

        # 3. Typhoon Refinement (using the SAME images)
        print(f"   2️⃣  Refining text with Typhoon...")
        
        total_blocks = 0
        refined_blocks = 0
        image_lock = threading.Lock()
        
        for p in temp_pages:
            page_no = p["page_no"]
            page_data = combined_result["pages"].get(page_no, {})
            blocks = page_data.get("blocks", [])
            
            if not blocks:
                continue
            
            # Load image
            try:
                pil_img = PILImage.open(p["path"])
            except Exception as e:
                print(f"      ⚠️ Could not load image {p['path']}: {e}")
                continue
            
            # Process blocks with Typhoon (sequentially for stability)
            for block in blocks:
                total_blocks += 1
                if self._refine_block_text(block, pil_img, image_lock):
                    refined_blocks += 1

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

    def _refine_block_text(self, block: Dict, full_page_img, image_lock) -> bool:
        """Refine text of a specific block using Typhoon OCR"""
        from typhoon_ocr import ocr_document
        import tempfile
        import re

        bbox = block["bbox"]
        x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
        
        # Add small padding to avoid cutting text edges
        padding = 10
        x1 = max(0, x1 - padding)
        y1 = max(0, y1 - padding)
        x2 = min(full_page_img.width, x2 + padding)
        y2 = min(full_page_img.height, y2 + padding)
        
        if (x2 - x1) < 10 or (y2 - y1) < 10:
            return False
            
        # Crop safely using lock
        try:
            with image_lock:
                crop_img = full_page_img.crop((x1, y1, x2, y2))
                crop_img.load()
        except Exception as e:
            print(f"      ⚠️ Failed to crop image: {e}")
            return False
        
        # Save to temp file
        temp_fd, temp_path = tempfile.mkstemp(suffix='.jpg')
        os.close(temp_fd)
        
        try:
            crop_img = crop_img.convert('RGB')
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
            # Call Typhoon OCR on cropped image
            text = ocr_document(temp_path, page_num=1)
            
            if text and len(text.strip()) > 0:
                # Clean up text
                text = text.strip()
                
                # Remove markdown artifacts
                text = text.replace('**', '').replace('##', '')
                
                # Remove XML-like tags (Typhoon hallucinations)
                text = re.sub(r'<page_number>.*?</page_number>', '', text, flags=re.IGNORECASE)
                text = re.sub(r'<pagination>.*?</pagination>', '', text, flags=re.IGNORECASE)
                text = re.sub(r'<[^>]+>', '', text)
                
                text = text.strip()
                
                if not text:
                    return False

                # Update block text with Typhoon's more accurate result
                block["text"] = text
                return True
                
        except Exception as e:
            print(f"      ⚠️ Refinement error: {e}")
            return False
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
        
        return False
