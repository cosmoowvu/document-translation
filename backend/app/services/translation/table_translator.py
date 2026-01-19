"""
Table Translator Module
Handles table-specific translation logic
"""
from typing import List, Dict

from app.services.text_processor import normalize_text, should_translate
from app.services.llm_service import LLMService
from app.services.translation.nllb_service import nllb_translator

TABLE_CELLS_PER_BATCH = 6  # จำนวน cells สูงสุดต่อ batch


class TableTranslator:
    """
    Handles table cell translation with batch support
    """
    def __init__(self, llm_service: LLMService):
        self.llm = llm_service
    
    def translate_cells(
        self,
        cells: List[Dict],
        target_lang: str,
        use_nllb_refine: bool = False,
        refine_model: str = None
    ) -> List[Dict]:
        """
        แปล cells ในตาราง
        - ใช้ batch translation
        - รองรับ NLLB+Refine mode
        """
        if not cells:
            return []
        
        results = []
        to_translate = []
        
        # แยก cells ที่ต้องแปล
        for cell in cells:
            text = normalize_text(cell.get('text', ''))
            need, detected_lang = should_translate(text, target_lang)
            
            if need and text:
                to_translate.append({
                    **cell,
                    'original_text': text,
                    'detected_lang': detected_lang
                })
            else:
                results.append({
                    **cell,
                    'translated': text,
                    'detected_lang': detected_lang,
                    'was_translated': False
                })
        
        if not to_translate:
            return results
        
        # แปล batch
        texts = [c['original_text'] for c in to_translate]
        src_lang = to_translate[0]['detected_lang'] if to_translate else 'tha_Thai'
        
        translated_texts = []
        chunk_size = TABLE_CELLS_PER_BATCH
        
        print(f"   📊 Table: {len(texts)} cells, {(len(texts) + chunk_size - 1) // chunk_size} batches (ละ {chunk_size})")
        
        for i in range(0, len(texts), chunk_size):
            chunk = texts[i:i + chunk_size]
            batch_num = (i // chunk_size) + 1
            total_batches = (len(texts) + chunk_size - 1) // chunk_size
            
            print(f"   🔄 Batch {batch_num}/{total_batches}: cells {i+1}-{i+len(chunk)}")
            
            if use_nllb_refine and refine_model:
                # NLLB+Refine mode
                print(f"      🌐 NLLB Translate...")
                nllb_results = nllb_translator.translate_batch(chunk, src_lang=src_lang, tgt_lang=target_lang)
                
                print(f"      ✨ LLM Refine with {refine_model}...")
                original_model = self.llm.model
                self.llm.model = refine_model
                
                if "gemma" in refine_model.lower():
                    chunk_results = self.llm.refine_batch_gemma(nllb_results, target_lang)
                else:
                    chunk_results = self.llm.refine_batch_qwen(nllb_results, target_lang)
                
                self.llm.model = original_model
            else:
                # Direct LLM translation
                chunk_results = self.llm.translate_batch_llm(chunk, target_lang, src_lang)
            
            translated_texts.extend(chunk_results)
        
        # รวมผลลัพธ์
        for i, cell in enumerate(to_translate):
            translated = translated_texts[i] if i < len(translated_texts) else cell['original_text']
            if not translated.strip():
                translated = cell['original_text']
                
            results.append({
                'text': cell.get('text', ''),
                'row': cell['row'],
                'col': cell['col'],
                'translated': translated,
                'detected_lang': cell['detected_lang'],
                'was_translated': True
            })
        
        # เรียงตาม row, col
        results.sort(key=lambda x: (x['row'], x['col']))
        return results
    
    def translate_tables(
        self,
        tables: List[Dict],
        target_lang: str,
        use_nllb_refine: bool = False,
        refine_model: str = None
    ) -> List[Dict]:
        """แปลทุกตารางในหน้า"""
        if not tables:
            return []
        
        translated_tables = []
        for table in tables:
            cells = table.get('cells', [])
            translated_cells = self.translate_cells(
                cells,
                target_lang,
                use_nllb_refine=use_nllb_refine,
                refine_model=refine_model
            )
            
            translated_tables.append({
                **table,
                'cells': translated_cells
            })
            
            if translated_cells:
                print(f"      📊 Table {table.get('num_rows', 0)}x{table.get('num_cols', 0)}: {len(translated_cells)} cells translated")
        
        return translated_tables
