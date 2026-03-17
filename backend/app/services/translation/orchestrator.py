"""
Translation Orchestrator
Main coordinator for all translation workflows
"""
from typing import List, Dict, Tuple

from app.config import settings
from app.services.llm_service import LLMService
from .table_translator import TableTranslator
from .batch_translator import BatchTranslator


class TranslationOrchestrator:
    """
    Main orchestrator that coordinates all translation types
    (Refactored to support Typhoon Only)
    """
    def __init__(self):
        self.llm = LLMService()
        self.table_translator = TableTranslator(self.llm)
    
    def translate_blocks_typhoon(
        self,
        blocks: List[Dict],
        target_lang: str,
        source_lang: str = "tha_Thai",
        job_status: dict = None,
        job_id: str = None
    ) -> Tuple[List[Dict], Dict]:
        """
        Typhoon Direct translation for Thai ↔ English
        Uses specialized translate_batch_typhoon method
        """
        # Delegate to BatchTranslator (which now uses Typhoon and handles splitting)
        translator = BatchTranslator(self.llm, batch_size=3)
        
        # Translate
        return translator.translate_blocks(
            blocks, 
            target_lang,
            source_lang=source_lang,  # Forward source_lang
            job_status=job_status,
            job_id=job_id
        )
    
    def translate_tables(
        self,
        tables: List[Dict],
        target_lang: str
    ) -> List[Dict]:
        """Translate table cells"""
        return self.table_translator.translate_tables(
            tables,
            target_lang
        )


# Singleton instance
translation_service = TranslationOrchestrator()
