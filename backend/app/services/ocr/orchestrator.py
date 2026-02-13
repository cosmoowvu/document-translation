"""
OCR Service Orchestrator
Routes document processing to the appropriate OCR engine
"""
from typing import Dict, Any
import os

from .docling_service import DoclingOCRService
from .typhoon_service import TyphoonOCRService
from .hybrid_service import HybridOCRService


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
        self._typhoon = None  # Lazy load
        self._hybrid = None   # Lazy load
    
    def process_document(
        self, 
        file_path: str, 
        source_lang: str = "tha_Thai",
        ocr_engine: str = "docling"
    ) -> Dict[str, Any]:
        """
        Process document ด้วย OCR engine ที่เลือก
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
                        result["ocr_engine"] = "Docling (Fallback)"
                        return result
                
                # Try Typhoon OCR
                try:
                    result = self._typhoon.process_document(file_path, source_lang)
                    result["ocr_engine"] = "typhoon-api (auto)"
                    return result
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"⚠️ Typhoon OCR failed: {e}")
                    print(f"🔄 Falling back to Docling...")
    def process_document(
        self,
        file_path: str,
        source_lang: str = "tha_Thai",
        ocr_engine: str = "docling",
        job_id: str = None  # ✅ Add optional job_id
    ) -> Dict[str, Any]:
        """
        Process the document and extract text blocks.
        Routing logic based on `ocr_engine`.
        """
        print(f"🔍 Orchestrator Processing with Engine: {ocr_engine}")
        
        if ocr_engine == "typhoon":
            # Direct Typhoon OCR Cloud
            # Lazy load Typhoon service
            if self._typhoon is None:
                try:
                    self._typhoon = TyphoonOCRService()
                except ValueError as e:
                    print(f"⚠️ Typhoon OCR not configured: {e}")
                    print(f"🔄 Falling back to Docling...")
                    result = self._docling.process_document(file_path, source_lang)
                    result["ocr_engine"] = "Docling (Fallback)"
                    return result
            return self._typhoon.process_document(file_path, source_lang)
            
        elif ocr_engine == "hybrid":
            # Hybrid: Docling Local + Typhoon Correction
            # For now, just alias to typhoon or docling. 
            # In real hybrid, we might run Docling first, then fix with LLM.
            # But here, user treats 'hybrid' as a distinct mode.
            # Let's map 'hybrid' to Docling for layout + Typhoon for Text?
            # Or just use Typhoon directly?
            # Based on user context, 'Hybrid' usually implies Docling + LLM Correction.
            # Here we just route to docling for now, since Correction happens in 'Translation' phase.
            return self._docling.process_document(file_path, source_lang)
        
        elif ocr_engine == "paddleocr":
            return self._paddle.process_document(file_path, source_lang)
            
        elif ocr_engine == "opencv":
            # ✅ OpenCV Mode
            # Lazy load
            if not hasattr(self, '_opencv') or self._opencv is None:
                from .opencv_service import OpenCVService
                self._opencv = OpenCVService()
                
            return self._opencv.process_document(file_path, source_lang, job_id=job_id)
            
        else:
            return self._docling.process_document(file_path, source_lang)


# Singleton instance
ocr_service = OCRService()
