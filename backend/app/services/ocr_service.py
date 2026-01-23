"""
OCR Service
รวม Docling OCR และ PaddleOCR ไว้ในไฟล์เดียว
- Docling: ใช้ EasyOCR ผ่าน Docling library (รันใน process เดียวกัน)
- PaddleOCR: เรียก external service ที่ port 8001 (แยก environment)
"""
from typing import List, Dict, Any
import os


class DoclingOCRService:
    """Docling OCR with EasyOCR backend"""
    
    def __init__(self):
        self._converters = {}
    
    def _has_text_layer(self, file_path: str) -> bool:
        """
        ตรวจสอบว่า PDF มี text layer ที่ดึงได้หรือไม่
        Returns True ถ้ามี text layer, False ถ้าเป็น scanned PDF
        """
        if not file_path.lower().endswith('.pdf'):
            return False
        
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            
            # เช็ค 3 หน้าแรก (หรือทั้งหมดถ้าน้อยกว่า 3)
            pages_to_check = min(3, len(doc))
            total_text_length = 0
            
            for page_num in range(pages_to_check):
                text = doc[page_num].get_text().strip()
                total_text_length += len(text)
            
            doc.close()
            
            # ถ้ามี text มากกว่า 50 ตัวอักษร = มี text layer
            has_text = total_text_length > 50
            return has_text
            
        except Exception as e:
            print(f"   ⚠️ Error checking text layer: {e}")
            return False  # ถ้าเช็คไม่ได้ให้เปิด OCR เผื่อไว้
    
    def _preprocess_image(self, file_path: str) -> str:
        """
        Pre-process image for better OCR accuracy
        Returns path to processed image (temp file)
        
        ⚠️ DISABLED aggressive preprocessing (binary thresholding)
        - Reason: Destroys colorful infographics, educational materials, slides
        - Old approach: CLAHE + Adaptive Threshold → binary image (black/white only)
        - New approach: Minimal preprocessing (slight sharpening only)
        """
        try:
            import cv2
            import tempfile
            import os
            
            # Read image
            img = cv2.imread(file_path)
            if img is None:
                print(f"   ⚠️ Failed to read image: {file_path}")
                return file_path
            
            # ✅ NEW: Minimal preprocessing - only slight sharpening for text clarity
            # Create sharpening kernel
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            kernel = kernel / kernel.sum()  # Normalize
            
            # Apply very light sharpening (preserves colors)
            sharpened = cv2.filter2D(img, -1, kernel)
            
            # Save to temporary file (preserving color depth)
            temp_fd, temp_path = tempfile.mkstemp(suffix='.png')
            os.close(temp_fd)  # Close file descriptor
            cv2.imwrite(temp_path, sharpened, [cv2.IMWRITE_PNG_COMPRESSION, 3])  # Light compression
            
            print(f"   🔧 Pre-processed image (minimal, color-preserving) → {temp_path}")
            return temp_path
            
        except Exception as e:
            print(f"   ⚠️ Pre-processing failed: {e}, using original image")
            return file_path
    
    def _get_converter(self, source_lang: str = "tha_Thai", skip_ocr: bool = False):
        """โหลด Docling Converter พร้อม EasyOCR (lazy loading, per language)"""
        
        # Map source_lang to EasyOCR language codes
        # EasyOCR uses short codes: 'th' for Thai, 'en' for English, etc.
        lang_map = {
            "tha_Thai": ["th", "en"],  # Thai + English (for mixed content)
            "eng_Latn": ["en"],
            "zho_Hans": ["ch_sim", "en"],
            "jpn_Jpan": ["ja", "en"],
            "kor_Hang": ["ko", "en"]
        }
        easyocr_langs = lang_map.get(source_lang, ["en"])
        
        # ✅ Include skip_ocr in cache key
        cache_key = f"{'_'.join(easyocr_langs)}_ocr{not skip_ocr}"
        
        if cache_key not in self._converters:
            ocr_mode = "text extraction" if skip_ocr else "OCR"
            print(f"📥 กำลังโหลด Docling ({ocr_mode}, EasyOCR {easyocr_langs})... (ครั้งแรกอาจใช้เวลาสักครู่)")
            
            from docling.document_converter import DocumentConverter, PdfFormatOption, ImageFormatOption
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.datamodel.pipeline_options import EasyOcrOptions
            
            # EasyOCR options for both PDF and Image
            easyocr_options = EasyOcrOptions(
                force_full_page_ocr=False,  # ✅ Let Docling extract text layer first (more accurate than OCR)
                lang=easyocr_langs  # EasyOCR language codes
            )
            
            # PDF Pipeline options
            pdf_pipeline_options = PdfPipelineOptions()
            pdf_pipeline_options.do_ocr = not skip_ocr  # ✅ Dynamic OCR enable/disable
            pdf_pipeline_options.do_table_structure = True
            pdf_pipeline_options.ocr_options = easyocr_options
            
            # ✅ Add both PDF and IMAGE format options with same EasyOCR settings
            self._converters[cache_key] = DocumentConverter(
                format_options={
                    "pdf": PdfFormatOption(pipeline_options=pdf_pipeline_options),
                    "image": ImageFormatOption(pipeline_options=pdf_pipeline_options)
                }
            )
            print(f"✅ Docling ({ocr_mode}) พร้อมใช้งาน")
        
        return self._converters[cache_key]
    
    def process_document(self, file_path: str, source_lang: str = "tha_Thai") -> Dict[str, Any]:
        """Process document และดึง text blocks + tables"""
        from docling_core.types.doc import DocItemLabel
        import os
        
        # ✅ Check if PDF has text layer
        skip_ocr = self._has_text_layer(file_path)
        
        if skip_ocr:
            print(f"   ✅ PDF has text layer - using text extraction only (faster)")
        else:
            print(f"   📸 Scanned PDF/Image detected - enabling OCR")
        
        # ✅ Pre-process image if OCR is needed
        processed_path = file_path
        temp_file_created = False
        
        if not skip_ocr:
            # Only pre-process images (not PDFs, even scanned ones)
            if not file_path.lower().endswith('.pdf'):
                print(f"   🔧 Pre-processing image for better OCR accuracy...")
                processed_path = self._preprocess_image(file_path)
                temp_file_created = (processed_path != file_path)
        
        # ✅ Pass skip_ocr to get correct converter
        converter = self._get_converter(source_lang, skip_ocr=skip_ocr)
        result = converter.convert(processed_path)
        doc = result.document
        
        # ✅ Clean up temporary preprocessed file
        if temp_file_created and os.path.exists(processed_path):
            try:
                os.unlink(processed_path)
                print(f"   🗑️ Cleaned up temp file: {processed_path}")
            except Exception as e:
                print(f"   ⚠️ Failed to delete temp file: {e}")
        
        num_pages = len(doc.pages)
        pages = {}
        
        for page_no in range(1, num_pages + 1):
            page = doc.pages[page_no]
            blocks = self._extract_blocks(doc, page_no, page.size.height, DocItemLabel)
            tables = self._extract_tables(doc, page_no, page.size.height)
            
            print(f"   🔍 Page {page_no}: Detected {len(tables)} tables, {len(blocks)} blocks")
            
            pages[page_no] = {
                "width": page.size.width,
                "height": page.size.height,
                "blocks": blocks,
                "tables": tables
            }
        
        return {
            "num_pages": num_pages,
            "pages": pages,
            "ocr_engine": "docling"
        }
    
    def _extract_blocks(self, doc, page_no: int, page_height: float, DocItemLabel) -> List[Dict]:
        """ดึง text blocks จากหน้าที่กำหนด (with smart duplicate detection)"""
        blocks = []
        
        def _bbox_overlap(bbox1, bbox2, threshold=0.1):  # ✅ Lowered to 0.1 (catch blocks with 10%+ overlap)
            """Check if two bboxes overlap significantly (>threshold)"""
            x_overlap = max(0, min(bbox1["x2"], bbox2["x2"]) - max(bbox1["x1"], bbox2["x1"]))
            y_overlap = max(0, min(bbox1["y2"], bbox2["y2"]) - max(bbox1["y1"], bbox2["y1"]))
            
            overlap_area = x_overlap * y_overlap
            bbox1_area = (bbox1["x2"] - bbox1["x1"]) * (bbox1["y2"] - bbox1["y1"])
            bbox2_area = (bbox2["x2"] - bbox2["x1"]) * (bbox2["y2"] - bbox2["y1"])
            
            if bbox1_area == 0 or bbox2_area == 0:
                return False
            
            # IoU (Intersection over Union)
            union_area = bbox1_area + bbox2_area - overlap_area
            iou = overlap_area / union_area if union_area > 0 else 0
            
            return iou > threshold
        
        for item in doc.texts:
            if item.label in [DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER]:
                continue
            
            if item.prov:
                for prov in item.prov:
                    if prov.page_no == page_no:
                        text = item.text.strip()
                        bbox_tl = prov.bbox.to_top_left_origin(page_height=page_height)
                        
                        new_bbox = {
                            "x1": bbox_tl.l,
                            "y1": bbox_tl.t,
                            "x2": bbox_tl.r,
                            "y2": bbox_tl.b
                        }
                        
                        # ✅ Simple text-only deduplication
                        # If text already seen → skip (regardless of bbox)
                        is_duplicate = False
                        for existing_block in blocks:
                            if existing_block["text"] == text:
                                is_duplicate = True
                                print(f"      ⚠️ Skipped duplicate text: '{text[:50]}...'")
                                break
                        
                        if not is_duplicate:
                            blocks.append({
                                "text": text,
                                "bbox": new_bbox,
                                "label": str(item.label) if item.label else "text"
                            })
        
        return blocks
    
    def _extract_tables(self, doc, page_no: int, page_height: float) -> List[Dict]:
        """ดึงตารางจาก DoclingDocument สำหรับหน้าที่กำหนด"""
        tables = []
        
        for table in doc.tables:
            if table.prov:
                for prov in table.prov:
                    if prov.page_no == page_no:
                        cells = []
                        num_rows = 0
                        num_cols = 0
                        
                        if hasattr(table, 'data') and table.data:
                            num_rows = table.data.num_rows if hasattr(table.data, 'num_rows') else 0
                            num_cols = table.data.num_cols if hasattr(table.data, 'num_cols') else 0
                            
                            if hasattr(table.data, 'grid'):
                                for row_idx, row in enumerate(table.data.grid):
                                    for col_idx, cell in enumerate(row):
                                        cell_text = cell.text if hasattr(cell, 'text') else str(cell)
                                        if cell_text and cell_text.strip():
                                            cells.append({
                                                'text': cell_text,
                                                'row': row_idx,
                                                'col': col_idx
                                            })
                        
                        bbox_tl = prov.bbox.to_top_left_origin(page_height=page_height)
                        tables.append({
                            'bbox': {
                                "x1": bbox_tl.l,
                                "y1": bbox_tl.t,
                                "x2": bbox_tl.r,
                                "y2": bbox_tl.b
                            },
                            'page': prov.page_no,
                            'num_rows': num_rows,
                            'num_cols': num_cols,
                            'cells': cells
                        })
        
        return tables


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
        
        print(f"🌪️ Using Typhoon OCR (Cloud API)")
        
        # Determine file type and page count
        file_ext = os.path.splitext(file_path)[1].lower()
        is_pdf = file_ext == '.pdf'
        
        if is_pdf:
            # Get PDF page count and dimensions
            try:
                import fitz  # PyMuPDF
                pdf_doc = fitz.open(file_path)
                num_pages = len(pdf_doc)
                
                # Get first page dimensions (assuming all pages same size)
                first_page = pdf_doc[0]
                page_width = first_page.rect.width  # in points
                page_height = first_page.rect.height
                pdf_doc.close()
            except ImportError:
                # Fallback: use pypdf
                from pypdf import PdfReader
                reader = PdfReader(file_path)
                num_pages = len(reader.pages)
                
                # Get first page dimensions
                first_page = reader.pages[0]
                mediabox = first_page.mediabox
                page_width = float(mediabox.width)
                page_height = float(mediabox.height)
        else:
            # For images, get actual image dimensions
            num_pages = 1
            with PILImage.open(file_path) as img:
                # Convert pixels to points (assuming 72 DPI for consistency)
                # If image has DPI info, use it; otherwise assume 72 DPI
                dpi = img.info.get('dpi', (72, 72))
                if isinstance(dpi, tuple):
                    dpi = dpi[0]
                
                # Calculate dimensions in points
                page_width = (img.width / dpi) * 72
                page_height = (img.height / dpi) * 72
                
                print(f"   📐 Image dimensions: {img.width}x{img.height}px @ {dpi} DPI → {page_width:.1f}x{page_height:.1f} points")
        
        print(f"   📄 Processing {num_pages} page(s)... ({page_width:.1f}x{page_height:.1f} points)")
        
        # Process each page
        pages = {}
        for page_no in range(1, num_pages + 1):
            print(f"   🔍 Page {page_no}/{num_pages}...")
            
            try:
                # Call Typhoon OCR API
                markdown_text = ocr_document(
                    pdf_or_image_path=file_path,
                    page_num=page_no
                )
                
                print(f"   ✅ Page {page_no}: Extracted {len(markdown_text)} characters")
                
                # ✅ Use single block with actual page dimensions
                margin_inches = 1
                margin_points = margin_inches * 72
                
                blocks = [{
                    "text": markdown_text,
                    "bbox": {
                        "x1": margin_points,
                        "y1": margin_points,
                        "x2": page_width - margin_points,
                        "y2": page_height - margin_points
                    },
                    "label": "text"
                }] if markdown_text else []
                
                pages[page_no] = {
                    "width": page_width,   # ✅ Use actual width (no expansion)
                    "height": page_height,  # ✅ Use actual height (no expansion)
                    "blocks": blocks,
                    "tables": []  # TODO: Parse markdown tables
                }
                
            except Exception as e:
                print(f"   ❌ Page {page_no} failed: {e}")
                raise
        
        return {
            "num_pages": num_pages,
            "pages": pages,
            "ocr_engine": "typhoon-api"
        }


class PaddleOCRService:
    """PaddleOCR via external microservice (port 8001)"""
    
    def __init__(self):
        self.service_url = "http://localhost:8001/process"
    
    def process_document(self, file_path: str, source_lang: str = "tha_Thai") -> Dict[str, Any]:
        """Send document to external PaddleOCR service"""
        import requests
        
        # PaddleOCR 2.7.x supported languages: ch, en, korean, japan, chinese_cht, ta, te, ka, latin, arabic, cyrillic, devanagari
        # Thai is not directly supported, use 'en' as fallback (still works for mixed Thai/English)
        lang_map = {
            "tha_Thai": "en",  # Thai not supported, use English model
            "eng_Latn": "en",
            "zho_Hans": "ch",
            "jpn_Jpan": "japan",
            "kor_Hang": "korean"
        }
        paddle_lang = lang_map.get(source_lang, "en")
        
        print(f"📤 Sending to PaddleOCR Service ({paddle_lang})...")
        
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f)}
            data = {'lang': paddle_lang}
            # ✅ Increased timeout for large PDFs (5 minutes)
            response = requests.post(self.service_url, files=files, data=data, timeout=300)
        
        if response.status_code == 200:
            print("✅ PaddleOCR Service responded successfully")
            result = response.json()
            
            # ✅ Fix: Convert string page keys to integers (JSON spec requires string keys)
            if "pages" in result:
                normalized_pages = {}
                for key, value in result["pages"].items():
                    # Convert string key to int
                    int_key = int(key) if isinstance(key, str) and key.isdigit() else key
                    normalized_pages[int_key] = value
                result["pages"] = normalized_pages
            
            return result
        else:
            raise Exception(f"Service returned status {response.status_code}: {response.text}")


class OCRService:
    """Orchestrator สำหรับเลือกใช้ OCR engine"""
    
    def __init__(self):
        self._docling = DoclingOCRService()
        self._paddle = PaddleOCRService()
        self._typhoon = None  # Lazy load (requires API key)
    
    def process_document(
        self, 
        file_path: str, 
        source_lang: str = "tha_Thai",
        ocr_engine: str = "docling"
    ) -> Dict[str, Any]:
        """
        Process document ด้วย OCR engine ที่เลือก
        
        Args:
            file_path: Path to document
            source_lang: Language code (e.g. "tha_Thai", "eng_Latn")
            ocr_engine: "docling", "paddleocr", "typhoon", หรือ "default"
        """
        # ✅ Handle "default" option - auto-detect based on file type
        if ocr_engine == "default":
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.pdf':
                # PDF files -> use Docling
                print(f"📸 Auto-detected PDF file -> Using Docling")
                result = self._docling.process_document(file_path, source_lang)
                result["ocr_engine"] = "docling (auto)"
                return result
            elif file_ext in ['.jpg', '.jpeg', '.png']:
                # Image files -> use Typhoon OCR
                print(f"📸 Auto-detected Image file -> Using Typhoon OCR")
                
                # Lazy load Typhoon service
                if self._typhoon is None:
                    try:
                        self._typhoon = TyphoonOCRService()
                    except ValueError as e:
                        print(f"⚠️ Typhoon OCR not configured: {e}")
                        print(f"🔄 Falling back to Docling...")
                        result = self._docling.process_document(file_path, source_lang)
                        result["ocr_engine"] = "docling (typhoon not configured)"
                        return result
                
                # Try Typhoon OCR
                try:
                    result = self._typhoon.process_document(file_path, source_lang)
                    result["ocr_engine"] = "typhoon-api (auto)"
                    return result
                except Exception as e:
                    print(f"⚠️ Typhoon OCR failed: {e}")
                    print(f"🔄 Falling back to Docling...")
                    result = self._docling.process_document(file_path, source_lang)
                    result["ocr_engine"] = "docling (fallback from typhoon)"
                    return result
            else:
                # Unknown file type -> fallback to Docling
                print(f"📸 Unknown file type '{file_ext}' -> Defaulting to Docling")
                result = self._docling.process_document(file_path, source_lang)
                result["ocr_engine"] = "docling (auto)"
                return result
        
        # ✅ Original logic for explicit OCR engine selection
        print(f"📸 Using OCR Engine: {ocr_engine.upper()}")
        
        if ocr_engine == "typhoon":
            # Lazy load Typhoon service (only initialize if needed)
            if self._typhoon is None:
                try:
                    self._typhoon = TyphoonOCRService()
                except ValueError as e:
                    print(f"⚠️ Typhoon OCR not configured: {e}")
                    print(f"🔄 Falling back to Docling...")
                    result = self._docling.process_document(file_path, source_lang)
                    result["ocr_engine"] = "docling (typhoon not configured)"
                    return result
            
            # Try Typhoon OCR
            try:
                return self._typhoon.process_document(file_path, source_lang)
            except Exception as e:
                print(f"⚠️ Typhoon OCR failed: {e}")
                print(f"🔄 Falling back to Docling...")
                result = self._docling.process_document(file_path, source_lang)
                result["ocr_engine"] = "docling (fallback from typhoon)"
                return result
        
        elif ocr_engine == "paddleocr":
            try:
                return self._paddle.process_document(file_path, source_lang)
            except Exception as e:
                print(f"⚠️ PaddleOCR failed: {e}")
                print(f"🔄 Falling back to Docling...")
                result = self._docling.process_document(file_path, source_lang)
                result["ocr_engine"] = "docling (fallback)"
                return result
        else:
            return self._docling.process_document(file_path, source_lang)


# Singleton instance
ocr_service = OCRService()
