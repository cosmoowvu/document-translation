"""
OCR Service Orchestrator
Routes document processing to the appropriate OCR engine
"""
from typing import Dict, Any
import os

from .typhoon_service import TyphoonOCRService
# OpenCVService lazy loaded

class OCRService:
    """Orchestrator สำหรับเลือกใช้ OCR engine"""
    
    def __init__(self):
        self._typhoon = None  # Lazy load
        self._opencv = None   # Lazy load

    def process_document(
        self,
        file_path: str,
        source_lang: str = "tha_Thai",
        ocr_engine: str = "paddleocr",
        job_id: str = None,
        job_status: Dict = None
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
                    raise e # No fallback in strict mode
                    
            # ✅ Pass job_id and job_status
            return self._typhoon.process_document(file_path, source_lang, job_id=job_id, job_status=job_status)
            
        elif ocr_engine == "opencv":
            # ✅ OpenCV Mode
            # Lazy load
            if not hasattr(self, '_opencv') or self._opencv is None:
                from .opencv_service import OpenCVService
                self._opencv = OpenCVService()
                
            return self._opencv.process_document(file_path, source_lang, job_id=job_id, job_status=job_status)

        elif ocr_engine in ["paddle", "paddleocr"]:
            # ✅ Paddle Layout Mode (PicoDet + DBNet → block detection)
            if not hasattr(self, '_paddle_layout') or self._paddle_layout is None:
                from .paddle_layout_service import PaddleLayoutService
                self._paddle_layout = PaddleLayoutService()

            return self._paddle_layout.process_document(file_path, source_lang, job_id=job_id, job_status=job_status)
            
        else:
            # Default to OpenCV if unknown (or error)
             print(f"⚠️ Unknown engine '{ocr_engine}', defaulting to OpenCV")
             if not hasattr(self, '_opencv') or self._opencv is None:
                from .opencv_service import OpenCVService
                self._opencv = OpenCVService()
             return self._opencv.process_document(file_path, source_lang, job_id=job_id, job_status=job_status)


# Singleton instance
ocr_service = OCRService()
