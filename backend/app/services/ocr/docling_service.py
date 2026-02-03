"""
Docling OCR Service
Uses EasyOCR via Docling library (runs in same process)
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
                        
                        # Check for duplicates using text AND approximate location
                        is_duplicate = False
                        
                        for existing_block in blocks:
                            # Strict duplicate check: Same Text AND Significant Overlap
                            if existing_block["text"] == text:
                                if _bbox_overlap(existing_block["bbox"], new_bbox, threshold=0.5):
                                    is_duplicate = True
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
