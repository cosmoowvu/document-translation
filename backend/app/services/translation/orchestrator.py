"""
Translation Orchestrator
Main coordinator for all translation workflows
"""
from typing import List, Dict, Tuple

from app.config import settings
from app.services.llm_service import LLMService
from .batch_translator import BatchTranslator
from .nllb_refine import NLLBRefineTranslator
from .table_translator import TableTranslator


class TranslationOrchestrator:
    """
    Main orchestrator that coordinates all translation types
    """
    def __init__(self):
        self.llm = LLMService()
        self.batch_translator = BatchTranslator(self.llm, batch_size=settings.BATCH_SIZE)
        self.nllb_refine = NLLBRefineTranslator(self.llm)
        self.table_translator = TableTranslator(self.llm)
    
    def translate_blocks(
        self,
        blocks: List[Dict],
        target_lang: str,
        use_nllb_refine: bool = False,
        refine_model: str = None,
        job_status: dict = None,
        job_id: str = None,
        page_no: int = 1,
        total_pages: int = 1
    ) -> Tuple[List[Dict], Dict]:
        """
        Main entry point for block translation
        Delegates to appropriate translator based on mode
        """
        if use_nllb_refine and refine_model:
            return self.nllb_refine.translate_and_refine(
                blocks,
                target_lang,
                refine_model,
                job_status=job_status,
                job_id=job_id,
                page_no=page_no,
                total_pages=total_pages
            )
        else:
            return self.batch_translator.translate_blocks(blocks, target_lang)
    
    def translate_blocks_typhoon(
        self,
        blocks: List[Dict],
        target_lang: str,
        source_lang: str = "tha_Thai"
    ) -> Tuple[List[Dict], Dict]:
        """
        Typhoon Direct translation for Thai ↔ English
        Uses specialized translate_batch_typhoon method
        """
        from app.services.text_processor import normalize_text, should_translate
        
        translated_blocks = []
        stats = {"total": len(blocks), "translated": 0, "skipped": 0}
        
        if not blocks:
            return translated_blocks, stats
        
        to_translate = []
        
        for idx, block in enumerate(blocks):
            text = normalize_text(block["text"])
            need, detected_lang = should_translate(text, target_lang)
            
            if need and text:
                to_translate.append((idx, block, text, detected_lang))
            else:
                translated_blocks.append({
                    **block,
                    "original_text": block["text"],
                    "text": text,
                    "detected_lang": detected_lang,
                    "was_translated": False
                })
                stats["skipped"] += 1
        
        if not to_translate:
            return translated_blocks, stats
        
        # Translate with Typhoon in batches
        batch_size = 5
        for i in range(0, len(to_translate), batch_size):
            batch = to_translate[i:i + batch_size]
            texts = [text for (_, _, text, _) in batch]
            
            print(f"   🐘 Typhoon Batch {i//batch_size + 1}: {len(texts)} blocks")
            
            results = self.llm.translate_batch_typhoon(texts, target_lang, source_lang)
            
            for j, (orig_idx, block, text, detected_lang) in enumerate(batch):
                translated = results[j] if j < len(results) and results[j] else text
                
                translated_blocks.append({
                    **block,
                    "original_text": text,
                    "text": translated,
                    "detected_lang": detected_lang,
                    "was_translated": True
                })
                stats["translated"] += 1
        
        return translated_blocks, stats
    
    # Backward compatibility methods
    def translate_blocks_nllb_refine(
        self,
        blocks: List[Dict],
        target_lang: str,
        refine_model: str,
        source_lang: str = "eng_Latn",  # ✅ เพิ่มพารามิเตอร์ source_lang
        job_status: dict = None,
        job_id: str = None,
        page_no: int = 1,
        total_pages: int = 1
    ) -> Tuple[List[Dict], Dict]:
        """Backward compatibility: NLLB + Refine translation"""
        return self.nllb_refine.translate_and_refine(
            blocks,
            target_lang,
            refine_model,
            source_lang=source_lang,  # ✅ ส่งต่อ source_lang ไปยัง nllb_refine
            job_status=job_status,
            job_id=job_id,
            page_no=page_no,
            total_pages=total_pages
        )
    
    def translate_table_cells(
        self,
        cells: List[Dict],
        target_lang: str,
        use_nllb_refine: bool = False,
        refine_model: str = None
    ) -> List[Dict]:
        """Backward compatibility: Translate table cells"""
        return self.table_translator.translate_cells(
            cells,
            target_lang,
            use_nllb_refine=use_nllb_refine,
            refine_model=refine_model
        )
    
    def translate_tables(
        self,
        tables: List[Dict],
        target_lang: str,
        use_nllb_refine: bool = False,
        refine_model: str = None
    ) -> List[Dict]:
        """Translate table cells"""
        return self.table_translator.translate_tables(
            tables,
            target_lang,
            use_nllb_refine=use_nllb_refine,
            refine_model=refine_model
        )


# Singleton instance (backward compatibility)
translation_service = TranslationOrchestrator()
