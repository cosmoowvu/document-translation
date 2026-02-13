"""
OCR Service Module
Provides multiple OCR engines for document text extraction
"""

from .orchestrator import OCRService, ocr_service
from .typhoon_service import TyphoonOCRService
# from .opencv_service import OpenCVService # Keep internal or expose if needed

__all__ = [
    'OCRService',
    'ocr_service',
    'TyphoonOCRService',
]
