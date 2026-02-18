"""
Table Translator Module
Handles table-specific translation logic for both PDF and Image tables
"""
import re
from typing import List, Dict
from html.parser import HTMLParser

from app.services.text_processor import normalize_text, should_translate
from app.services.llm_service import LLMService
from app.services.translation.qwen_translator import translate_blocks_qwen
from app.services.translation.model_manager import unload_model, load_model, preload_model
from app.config import settings

TABLE_CELLS_PER_BATCH = 6  # จำนวน cells สูงสุดต่อ batch


class HTMLTableParser(HTMLParser):
    """Parse HTML table and extract cell contents"""
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_td = False
        self.in_th = False
        self.current_cell = []
        self.cells = []
        
    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
        elif tag in ('td', 'th'):
            self.in_td = True
            self.current_cell = []
    
    def handle_endtag(self, tag):
        if tag == 'table':
            self.in_table = False
        elif tag in ('td', 'th'):
            self.in_td = False
            self.cells.append(''.join(self.current_cell))
            
    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)


class TableTranslator:
    """
    Handles table cell translation with batch support (Typhoon Only)
    Supports both PDF tables (structured cells) and Image tables (HTML blocks)
    """
    def __init__(self, llm_service: LLMService):
        self.llm = llm_service
    
    def translate_html_table_block(
        self,
        html_table: str,
        target_lang: str,
        src_lang: str = "tha_Thai"
    ) -> str:
        """
        แปล HTML table block (จาก OCR รูปภาพ)
        รองรับข้อความที่อยู่ก่อนและหลัง table ด้วย
        
        Args:
            html_table: HTML table string with optional surrounding text
            target_lang: ภาษาเป้าหมาย
            src_lang: ภาษาต้นทาง
            
        Returns:
            ข้อความทั้งหมดที่แปลแล้ว (text + table + text)
        """
        if not html_table or '<table>' not in html_table.lower():
            return html_table
        
        # Split into: text_before | <table>...</table> | text_after
        table_pattern = r'(<table>.*?</table>)'
        parts = re.split(table_pattern, html_table, flags=re.IGNORECASE | re.DOTALL)
        
        # parts = ["text before", "<table>...</table>", "text after"]
        # or ["<table>...</table>"] if no surrounding text
        
        translated_parts = []
        
        for part in parts:
            if not part.strip():
                translated_parts.append(part)
                continue
            
            # Check if this part is a table
            if '<table>' in part.lower() and '</table>' in part.lower():
                # Translate table cells
                translated_table = self._translate_table_cells(part, target_lang, src_lang)
                translated_parts.append(translated_table)
            else:
                # Translate regular text
                translated_text = self._translate_text(part, target_lang, src_lang)
                translated_parts.append(translated_text)
        
        return ''.join(translated_parts)
    
    def translate_ocr_table_block(
        self,
        text: str,
        target_lang: str,
        src_lang: str = "tha_Thai"
    ) -> str:
        """
        [NEW] Translate raw OCR text (Markdown/Plain) => HTML Table
        Used when OpenCV detects a table but OCR returns text.
        """
        if not text.strip():
            return text
            
        print(f"   📊 Table Block (OCR Text): Translating {len(text)} chars -> HTML Table")
        
        # Construct Prompt
        # Force Typhoon to output HTML table
        prompt = (
            f"Translate the following text from {src_lang} to {target_lang}.\n"
            "The input is a table structure (could be Markdown, CSV, or loose text).\n"
            "CRITICAL RULES:\n"
            "1. Output the result as a valid HTML `<table>` structure.\n"
            "2. Preserve the rows and columns as best as possible.\n"
            "3. Do NOT add any explanations or markdown code blocks (```html).\n"
            "4. Output ONLY the HTML <table>...</table> code.\n\n"
            f"Input:\n{text}\n\n"
            "Output (HTML Table):"
        )
        
        try:
            # Call LLM directly (no batching for full table reconstruction)
            # Use lower temperature for structure preservation
            response = self.llm.generate(
                prompt, 
                temperature=0.1, 
                max_tokens=2048
            )
            
            # Extract table if wrapped in markdown
            match = re.search(r'<table>.*?</table>', response, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(0)
            
            # If no table tags found, but has <tr>...
            if '<tr>' in response:
                return f"<table>{response}</table>"
                
            return response # Fallback: return raw response (hope it's table-like)
            
        except Exception as e:
            print(f"      ⚠️ Failed to translate OCR table: {e}")
            return text

    def _translate_table_cells(
        self,
        table_html: str,
        target_lang: str,
        src_lang: str
    ) -> str:
        """แปล cells ภายใน HTML table"""
        # Parse HTML table to extract cells
        parser = HTMLTableParser()
        try:
            parser.feed(table_html)
        except Exception as e:
            print(f"   ⚠️ Failed to parse HTML table: {e}")
            return table_html
        
        cells = parser.cells
        if not cells:
            return table_html
        
        print(f"   📊 HTML Table: Extracted {len(cells)} cells for translation")
        print(f"      📝 Sample cells: {cells[:3]}") # Debug
        
        # Detect language if auto
        if src_lang == "auto":
            # Sample text from cells (join first 20 cells)
            sample_text = " ".join(cells[:20])
            from app.services.text_processor import detect_language
            detected = detect_language(sample_text)
            
            # Use Hybrid Detection if ambiguous
            if detected in ["unknown", "eng_Latn"]:
                 has_cjk_thai = any('\u0e00' <= c <= '\u0e7f' or  # Thai
                                   '\u3040' <= c <= '\u30ff' or  # Japanese
                                   '\u4e00' <= c <= '\u9fff' or  # Chinese
                                   '\uac00' <= c <= '\ud7af'     # Korean
                                   for c in sample_text)
                 
                 if not has_cjk_thai and len(sample_text) > 20:
                     print("      🔍 Table language ambiguous, checking LLM...")
                     detected = self.llm.detect_language(sample_text[:500])
            
            src_lang = detected
            if src_lang == "unknown":
                # Detect script
                has_thai = any('\u0e00' <= c <= '\u0e7f' for c in sample_text)
                has_korean = any('\uac00' <= c <= '\ud7af' for c in sample_text)
                has_kana = any('\u3040' <= c <= '\u30ff' for c in sample_text)
                has_chinese = any('\u4e00' <= c <= '\u9fff' for c in sample_text)

                if has_thai: src_lang = "tha_Thai"
                elif has_korean: src_lang = "kor_Hang"
                elif has_kana: src_lang = "jpn_Jpan"
                elif has_chinese: src_lang = "zho_Hans"
                else: src_lang = "eng_Latn"
                print(f"      ⚠️ Defaulting unknown source -> {src_lang}")
            print(f"      🤖 Table Language Detected: {src_lang}")
        
        # แปลแต่ละ cell
        translated_cells = []
        chunk_size = TABLE_CELLS_PER_BATCH
        
        for i in range(0, len(cells), chunk_size):
            chunk = cells[i:i + chunk_size]
            batch_num = (i // chunk_size) + 1
            total_batches = (len(cells) + chunk_size - 1) // chunk_size
            
            print(f"   🔄 Batch {batch_num}/{total_batches}: cells {i+1}-{i+len(chunk)}")
            
            # Use Typhoon Direct
            chunk_results, failed_indices = self.llm.translate_batch_typhoon(chunk, target_lang, src_lang)
            print(f"      📝 Translated: {chunk_results}") # Debug
            
            # Post-validation: Check for wrong language
            forbidden_scripts = []
            if target_lang == "zho_Hans" or target_lang == "zho_Hant":
                forbidden_scripts = ['\u0e00-\u0e7f']  # Thai
            elif target_lang == "jpn_Jpan":
                forbidden_scripts = ['\u0e00-\u0e7f']  # Thai
            elif target_lang == "kor_Hang":
                forbidden_scripts = ['\u0e00-\u0e7f']  # Thai
            
            # Check each result for forbidden characters
            validated_results = []
            qwen_candidates_indices = [] # Indices within chunk that need Qwen retry
            
            for idx, (original, translated) in enumerate(zip(chunk, chunk_results)):
                # Check if Typhoon failed technically
                is_failed = (idx in failed_indices)
                
                # Check validation (forbidden chars)
                if not is_failed and forbidden_scripts and translated:
                    for script_range in forbidden_scripts:
                        if re.search(f'[{script_range}]', translated):
                            print(f"      ⚠️ Cell {i+idx+1}: Wrong language detected")
                            is_failed = True
                            break
                
                if is_failed:
                    qwen_candidates_indices.append(idx)
                    validated_results.append(original) # Placeholder
                else:
                    validated_results.append(translated)
            
            # --- Fallback: Qwen for failed cells ---
            if qwen_candidates_indices:
                print(f"      🚨 {len(qwen_candidates_indices)} cells failed validation - Switching to Qwen...")
                
                try:
                    # Model config
                    typhoon_model = "scb10x/typhoon-translate1.5-4b:latest"
                    qwen_model = "qwen2.5:3b"
                    
                    # Unload Typhoon / Load Qwen
                    unload_model(typhoon_model, settings.OLLAMA_URL)
                    load_model(qwen_model, settings.OLLAMA_URL)
                    
                    # Translate failed chunks
                    failed_texts = [chunk[idx] for idx in qwen_candidates_indices]
                    qwen_results, _ = translate_blocks_qwen(
                        failed_texts, target_lang, src_lang, settings.OLLAMA_URL, qwen_model
                    )
                    
                    # Merge results
                    for q_idx, original_idx in enumerate(qwen_candidates_indices):
                        if qwen_results[q_idx]:
                            validated_results[original_idx] = qwen_results[q_idx]
                            print(f"      ✅ Cell {i+original_idx+1} recovered by Qwen")
                        else:
                            print(f"      ❌ Cell {i+original_idx+1} failed even with Qwen")
                            
                    # Restore Typhoon
                    unload_model(qwen_model, settings.OLLAMA_URL)
                    preload_model(typhoon_model, settings.OLLAMA_URL)
                    
                except Exception as e:
                    print(f"      ⚠️ Qwen fallback error: {e}")
                    # Keep placeholders (original text)
            
            translated_cells.extend(validated_results)
        
        # Rebuild HTML table with translated cells
        rebuilt_html = table_html
        for i, (original, translated) in enumerate(zip(cells, translated_cells)):
            if original and translated:
                # Escape special regex characters in original text
                escaped_original = re.escape(original)
                # Replace cell content using lambda to avoid backreference issues
                pattern = f'(<t[dh][^>]*>){escaped_original}(</t[dh]>)'
                
                def replace_func(match):
                    return match.group(1) + translated + match.group(2)
                
                rebuilt_html = re.sub(
                    pattern,
                    replace_func,
                    rebuilt_html,
                    count=1,
                    flags=re.IGNORECASE
                )
        
        print(f"      ✅ HTML Table: Translated {len(translated_cells)}/{len(cells)} cells")
        return rebuilt_html
    
    def _translate_text(
        self,
        text: str,
        target_lang: str,
        src_lang: str
    ) -> str:
        """แปลข้อความทั่วไป (ไม่ใช่ table)"""
        if not text.strip():
            return text
        
        print(f"   📝 Text block: {len(text)} chars")
        
        # Detect language if auto
        if src_lang == "auto":
            from app.services.text_processor import detect_language
            detected = detect_language(text)
            
            # Use Hybrid Detection if ambiguous
            if detected in ["unknown", "eng_Latn"] and len(text) > 20:
                 has_cjk_thai = any('\u0e00' <= c <= '\u0e7f' or  # Thai
                                   '\u3040' <= c <= '\u30ff' or  # Japanese
                                   '\u4e00' <= c <= '\u9fff' or  # Chinese
                                   '\uac00' <= c <= '\ud7af'     # Korean
                                   for c in text)
                 
                 if not has_cjk_thai:
                     print("      🔍 Text language ambiguous, checking LLM...")
                     detected = self.llm.detect_language(text[:500])
            
            src_lang = detected
            print(f"      🤖 Text Language Detected: {src_lang}")
        
        # Use regular Typhoon translation
        results, failed_indices = self.llm.translate_batch_typhoon([text], target_lang, src_lang)
        
        # --- Fallback: Qwen if validation failed or result is empty ---
        needs_fallback = bool(failed_indices)
        if not results or not results[0]:
            needs_fallback = True
            
        if needs_fallback:
            print("      🚨 Text validation failed/rejected - Switching to Qwen...")
            try:
                # Model config
                typhoon_model = "scb10x/typhoon-translate1.5-4b:latest"
                qwen_model = "qwen2.5:3b"
                
                unload_model(typhoon_model, settings.OLLAMA_URL)
                load_model(qwen_model, settings.OLLAMA_URL)
                
                qwen_results, _ = translate_blocks_qwen(
                    [text], target_lang, src_lang, settings.OLLAMA_URL, qwen_model
                )
                
                # Restore Typhoon logic
                unload_model(qwen_model, settings.OLLAMA_URL)
                preload_model(typhoon_model, settings.OLLAMA_URL)
                
                if qwen_results and qwen_results[0]:
                     print("      ✅ Text recovered by Qwen")
                     return qwen_results[0]
                
            except Exception as e:
                print(f"      ⚠️ Qwen fallback error: {e}")

        # Even if validation fails, use the result (don't fallback to original)
        # The model tried to translate, even if imperfect
        if results and results[0]:
            if failed_indices:
                print(f"      ⚠️ Text validation failed but keeping translation attempt")
            return results[0]
        else:
            print(f"      ⚠️ Text translation produced no result, keeping original")
            return text
    
    def translate_cells(
        self,
        cells: List[Dict],
        target_lang: str,
        use_nllb_refine: bool = False,
        refine_model: str = None
    ) -> List[Dict]:
        """
        แปล cells ในตาราง PDF (Typhoon Direct)
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
        
        print(f"   📊 PDF Table: {len(texts)} cells, {(len(texts) + chunk_size - 1) // chunk_size} batches (ละ {chunk_size})")
        
        for i in range(0, len(texts), chunk_size):
            chunk = texts[i:i + chunk_size]
            batch_num = (i // chunk_size) + 1
            total_batches = (len(texts) + chunk_size - 1) // chunk_size
            
            print(f"   🔄 Batch {batch_num}/{total_batches}: cells {i+1}-{i+len(chunk)}")
            
            # Use Typhoon Direct (returns tuple: results, failed_indices)
            chunk_results, failed_indices = self.llm.translate_batch_typhoon(chunk, target_lang, src_lang)
            
            # Post-validation: Check for wrong language
            forbidden_scripts = []
            if target_lang == "zho_Hans" or target_lang == "zho_Hant":
                forbidden_scripts = ['\u0e00-\u0e7f']  # Thai
            elif target_lang == "jpn_Jpan":
                forbidden_scripts = ['\u0e00-\u0e7f']  # Thai
            elif target_lang == "kor_Hang":
                forbidden_scripts = ['\u0e00-\u0e7f']  # Thai
            
            # Validate each result
            validated_results = []
            for idx, (original_text, translated) in enumerate(zip(chunk, chunk_results)):
                has_forbidden = False
                if forbidden_scripts and translated:
                    for script_range in forbidden_scripts:
                        if re.search(f'[{script_range}]', translated):
                            has_forbidden = True
                            print(f"      ⚠️ Cell {i+idx+1}: Wrong language detected, using original")
                            break
                
                if has_forbidden:
                    validated_results.append(original_text)
                else:
                    validated_results.append(translated)
            
            # Log if any cells failed validation
            if failed_indices:
                print(f"      ⚠️ {len(failed_indices)} cells failed validation in this batch")
            
            translated_texts.extend(validated_results)
        
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
        """แปลทุกตารางในหน้า (สำหรับ PDF)"""
        if not tables:
            return []
        
        translated_tables = []
        for table in tables:
            cells = table.get('cells', [])
            translated_cells = self.translate_cells(
                cells,
                target_lang,
                use_nllb_refine=False,
                refine_model=None
            )
            
            translated_tables.append({
                **table,
                'cells': translated_cells
            })
            
            if translated_cells:
                print(f"      📊 Table {table.get('num_rows', 0)}x{table.get('num_cols', 0)}: {len(translated_cells)} cells translated")
        
        return translated_tables
