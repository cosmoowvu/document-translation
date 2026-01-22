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
    
    def _get_converter(self, source_lang: str = "tha_Thai"):
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
        cache_key = "_".join(easyocr_langs)
        
        if cache_key not in self._converters:
            print(f"📥 กำลังโหลด Docling (EasyOCR {easyocr_langs})... (ครั้งแรกอาจใช้เวลาสักครู่)")
            
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
            pdf_pipeline_options.do_ocr = True
            pdf_pipeline_options.do_table_structure = True
            pdf_pipeline_options.ocr_options = easyocr_options
            
            # ✅ Add both PDF and IMAGE format options with same EasyOCR settings
            self._converters[cache_key] = DocumentConverter(
                format_options={
                    "pdf": PdfFormatOption(pipeline_options=pdf_pipeline_options),
                    "image": ImageFormatOption(pipeline_options=pdf_pipeline_options)
                }
            )
            print(f"✅ Docling (EasyOCR {easyocr_langs}) พร้อมใช้งาน")
        
        return self._converters[cache_key]
    
    def process_document(self, file_path: str, source_lang: str = "tha_Thai") -> Dict[str, Any]:
        """Process document และดึง text blocks + tables"""
        from docling_core.types.doc import DocItemLabel
        
        # ✅ Pass source_lang to get correct EasyOCR language model
        converter = self._get_converter(source_lang)
        result = converter.convert(file_path)
        doc = result.document
        
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
        """ดึง text blocks จากหน้าที่กำหนด"""
        blocks = []
        
        for item in doc.texts:
            if item.label in [DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER]:
                continue
            
            if item.prov:
                for prov in item.prov:
                    if prov.page_no == page_no:
                        bbox_tl = prov.bbox.to_top_left_origin(page_height=page_height)
                        blocks.append({
                            "text": item.text,
                            "bbox": {
                                "x1": bbox_tl.l,
                                "y1": bbox_tl.t,
                                "x2": bbox_tl.r,
                                "y2": bbox_tl.b
                            },
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
        
        print(f"🌪️ Using Typhoon OCR (Cloud API)")
        
        # Determine file type and page count
        file_ext = os.path.splitext(file_path)[1].lower()
        is_pdf = file_ext == '.pdf'
        
        if is_pdf:
            # Get PDF page count
            try:
                import fitz  # PyMuPDF
                pdf_doc = fitz.open(file_path)
                num_pages = len(pdf_doc)
                pdf_doc.close()
            except ImportError:
                # Fallback: use pypdf (already installed with typhoon-ocr)
                from pypdf import PdfReader
                reader = PdfReader(file_path)
                num_pages = len(reader.pages)
        else:
            num_pages = 1
        
        print(f"   📄 Processing {num_pages} page(s)...")
        
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
                
                # Convert markdown to standardized block format
                # For now, treat entire markdown as one text block
                # TODO: Parse markdown to extract individual text blocks and tables
                
                # ✅ Add margins for Typhoon OCR (2 inches from edges)
                margin_inches = 2
                margin_points = margin_inches * 72  # 1 inch = 72 points
                
                blocks = [{
                    "text": markdown_text,
                    "bbox": {
                        "x1": margin_points,  # 2 inches from left
                        "y1": margin_points,  # 2 inches from top
                        "x2": 595 - margin_points,  # 2 inches from right (A4 width = 595)
                        "y2": 842 - margin_points   # 2 inches from bottom (A4 height = 842)
                    },
                    "label": "text"
                }] if markdown_text else []
                
                pages[page_no] = {
                    "width": 595,   # A4 width in points
                    "height": 842,  # A4 height in points
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
            ocr_engine: "docling", "paddleocr", หรือ "typhoon"
        """
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
