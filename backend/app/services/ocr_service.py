"""
OCR Service (Re-export from modular package)

⚠️ DEPRECATED: This file is kept for backwards compatibility.
   Please import from app.services.ocr instead:
   
   from app.services.ocr import ocr_service
"""

# Re-export from new modular package
from app.services.ocr import (
    OCRService,
    ocr_service,
    DoclingOCRService,
    TyphoonOCRService,
    HybridOCRService,
)

__all__ = [
    'OCRService',
    'ocr_service',
    'DoclingOCRService',
    'TyphoonOCRService',
    'HybridOCRService',
]
