"""
OCR Service Module
Provides multiple OCR engines for document text extraction
"""

from .orchestrator import OCRService, ocr_service
from .docling_service import DoclingOCRService
from .typhoon_service import TyphoonOCRService
from .hybrid_service import HybridOCRService

__all__ = [
    'OCRService',
    'ocr_service',
    'DoclingOCRService',
    'TyphoonOCRService',
    'HybridOCRService',
]
