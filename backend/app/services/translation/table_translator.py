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

# CJK target languages (used for leakage scope decisions)
_CJK_LANGS = {"jpn_Jpan", "ja", "zho_Hans", "zho_Hant", "zh", "zh-cn", "kor_Hang", "ko"}


def _get_source_leakage_scripts(src_lang: str, target_lang: str) -> list:
    """
    Return regex character ranges that should NOT appear in the translated output.
    Based on the SOURCE language — we check if source chars leaked into the translation.
    Returns empty list if no leakage check is needed (e.g. English source).
    """
    # Thai source: Sarabun/Thai chars shouldn't appear in output
    if src_lang in {"tha_Thai", "th"}:
        return [r'\u0e00-\u0e7f']

    # Japanese source: Hiragana + Katakana are unique to Japanese (Kanji overlaps ZH, skip)
    if src_lang in {"jpn_Jpan", "ja"}:
        # If target is also Japanese → no check (translation is in Japanese)
        if target_lang in {"jpn_Jpan", "ja"}:
            return []
        return [r'\u3040-\u309f', r'\u30a0-\u30ff']  # Hiragana + Katakana

    # Korean source: Hangul is unique to Korean
    if src_lang in {"kor_Hang", "ko"}:
        if target_lang in {"kor_Hang", "ko"}:
            return []
        return [r'\uac00-\ud7af']

    # Chinese source: CJK Unified chars — only check when target is non-CJK
    if src_lang in {"zho_Hans", "zho_Hant", "zh", "zh-cn"}:
        if target_lang in _CJK_LANGS:
            return []  # CJK→CJK overlap too complex, handled by Qwen3 final pass
        return [r'\u4e00-\u9fff']

    # English / Latin source → no leakage concern
    return []


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
        
        # 1. Try Typhoon First
        prompt = (
            f"You are a professional translator. Translate the content of the following table from {src_lang} to {target_lang}.\n"
            "The input is a table structure (Markdown, CSV, or spaces).\n"
            "CRITICAL RULES:\n"
            "1. Output the result as a valid HTML `<table>` structure with `<tr>` and `<td>`.\n"
            "2. TRANSLATE ALL TEXT content inside the cells significantly. Do NOT leave them in source language.\n"
            "3. Analyze vertical and horizontal alignment to preserve rows/columns.\n"
            "4. Output ONLY the HTML code. No markdown code blocks.\n\n"
            f"Input:\n{text}\n\n"
            "Output (HTML Table):"
        )
        
        translated_html = ""
        
        try:
            # Use slightly higher temp for better translation creativity (vs strict formatting)
            translated_html = self.llm.generate(prompt, temperature=0.1, max_tokens=2048)
            
            # Extract
            match = re.search(r'<table>.*?</table>', translated_html, re.DOTALL | re.IGNORECASE)
            if match:
                translated_html = match.group(0)
            elif '<tr>' in translated_html:
                translated_html = f"<table>{translated_html}</table>"
                
        except Exception as e:
            print(f"      ⚠️ Typhoon Table Error: {e}")
            translated_html = ""

        # 2. Validation
        is_valid = True
        
        # Check 1: Empty result
        if not translated_html or len(translated_html) < 10:
            is_valid = False
            print("      ❌ Table Validation Failed: Empty result")
            
        # Check 2: CJK Target Presence (If target is JPN/ZH/KO, output MUST contain appropriate scripts)
        # Use simple ranges
        if is_valid and target_lang in _CJK_LANGS:
            # Strip tags for check
            clean_text = re.sub(r'<[^>]+>', '', translated_html)
            
            has_cjk = False
            if target_lang in {"jpn_Jpan", "ja"}:
                # Check Kana or Kanji
                has_cjk = any('\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff' for c in clean_text)
            elif target_lang in {"zho_Hans", "zho_Hant", "zh", "zh-cn"}:
                # Check Chinese
                has_cjk = any('\u4e00' <= c <= '\u9fff' for c in clean_text)
            elif target_lang in {"kor_Hang", "ko"}:
                # Check Hangul
                has_cjk = any('\uac00' <= c <= '\ud7af' for c in clean_text)
            
            if not has_cjk and len(clean_text) > 0:
                is_valid = False
                print(f"      ❌ Table Validation Failed: No {target_lang} characters found in output")

        # 3. Fallback to Qwen if invalid
        if not is_valid:
            print("      🔄 Switching to Qwen for Table Translation...")
            try:
                from app.services.translation.model_manager import load_model, unload_model
                from app.config import settings
                from app.services.translation.qwen_translator import _generate_qwen
                
                # Unload Typhoon, Load Qwen
                typhoon_model = "scb10x/typhoon-translate1.5-4b:latest"
                qwen_model = settings.FALLBACK_MODEL
                
                unload_model(typhoon_model, settings.OLLAMA_URL)
                load_model(qwen_model, settings.OLLAMA_URL)
                
                # Qwen Prompt (Qwen likes concise instructions)
                qwen_prompt = (
                    f"Translate this table from {src_lang} to {target_lang}. \n"
                    "Output ONLY the HTML <table> structure. \n"
                    "Ensure all cell contents are translated.\n\n"
                    f"{text}"
                )
                
                qwen_html = _generate_qwen(qwen_prompt, settings.OLLAMA_URL, qwen_model)
                
                # Extract
                match = re.search(r'<table>.*?</table>', qwen_html, re.DOTALL | re.IGNORECASE)
                if match:
                    translated_html = match.group(0)
                elif '<tr>' in qwen_html:
                    translated_html = f"<table>{qwen_html}</table>"
                else:
                    translated_html = qwen_html # Best effort
                
                print("      ✅ Qwen Table Translation Completed")
                
                # Restore Typhoon
                unload_model(qwen_model, settings.OLLAMA_URL)
                preload_model(typhoon_model, settings.OLLAMA_URL)
                
            except Exception as e:
                print(f"      ⚠️ Qwen Fallback Failed: {e}")
                # Return original text or whatever we got
                if not translated_html:
                    return text
        
        return translated_html

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
            
            # Post-validation: Detect source language leakage in translated output
            forbidden_scripts = _get_source_leakage_scripts(src_lang, target_lang)

            # Check each result for forbidden characters
            validated_results = []
            qwen_candidates_indices = [] # Indices within chunk that need Qwen retry
            
            for idx, (original, translated) in enumerate(zip(chunk, chunk_results)):
                # Check if Typhoon failed technically
                is_failed = (idx in failed_indices)
                
                # Check validation (forbidden source chars)
                if not is_failed and forbidden_scripts and translated:
                    for script_range in forbidden_scripts:
                        if re.search(f'[{script_range}]', translated):
                            print(f"      ⚠️ Cell {i+idx+1}: Source leakage detected")
                            is_failed = True
                            break
                            
                # [NEW] Check validation (target language presence for CJK)
                # If target is CJK but result has NO CJK chars -> Failed (likely returned English)
                if not is_failed and translated and target_lang in _CJK_LANGS:
                    clean_text = re.sub(r'<[^>]+>', '', translated) # strip tags if any
                    has_cjk = False
                    if target_lang in {"jpn_Jpan", "ja"}:
                         has_cjk = any('\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff' for c in clean_text)
                    elif target_lang in {"zho_Hans", "zho_Hant", "zh", "zh-cn"}:
                         has_cjk = any('\u4e00' <= c <= '\u9fff' for c in clean_text)
                    elif target_lang in {"kor_Hang", "ko"}:
                         has_cjk = any('\uac00' <= c <= '\ud7af' for c in clean_text)
                    
                    if not has_cjk and len(clean_text.strip()) > 0:
                         # Only fail if original was NOT empty/symbol-only
                         # Check if original had meaningful text
                         if any(c.isalnum() for c in original):
                             print(f"      ⚠️ Cell {i+idx+1}: No CJK characters in output (Translation failed)")
                             is_failed = True
                
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
                    qwen_model = settings.FALLBACK_MODEL
                    
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
                qwen_model = settings.FALLBACK_MODEL
                
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
            
            # Post-validation: Detect source language leakage in translated output
            forbidden_scripts = _get_source_leakage_scripts(src_lang, target_lang)

            # Validate each result
            validated_results = []
            qwen_candidates_indices = []
            
            for idx, (original_text, translated) in enumerate(zip(chunk, chunk_results)):
                is_failed = (idx in failed_indices)
                has_forbidden = False
                
                # Check validation (forbidden source chars)
                if not is_failed and forbidden_scripts and translated:
                    for script_range in forbidden_scripts:
                        if re.search(f'[{script_range}]', translated):
                            has_forbidden = True
                            print(f"      ⚠️ Cell {i+idx+1}: Source lang leakage detected ({src_lang})")
                            break
                            
                # Check validation (target language presence for CJK)
                if not is_failed and not has_forbidden and translated and target_lang in _CJK_LANGS:
                    clean_text = re.sub(r'<[^>]+>', '', translated)
                    has_cjk = False
                    if target_lang in {"jpn_Jpan", "ja"}:
                         has_cjk = any('\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff' for c in clean_text)
                    elif target_lang in {"zho_Hans", "zho_Hant", "zh", "zh-cn"}:
                         has_cjk = any('\u4e00' <= c <= '\u9fff' for c in clean_text)
                    elif target_lang in {"kor_Hang", "ko"}:
                         has_cjk = any('\uac00' <= c <= '\ud7af' for c in clean_text)
                    
                    if not has_cjk and len(clean_text.strip()) > 0:
                         if any(c.isalnum() for c in original_text):
                             print(f"      ⚠️ Cell {i+idx+1}: No CJK characters in output")
                             has_forbidden = True

                if has_forbidden or is_failed:
                    validated_results.append(original_text) # Placeholder
                    qwen_candidates_indices.append(idx)
                else:
                    validated_results.append(translated)

            # --- Fallback: Qwen for failed cells ---
            if qwen_candidates_indices:
                print(f"      🚨 {len(qwen_candidates_indices)} cells failed validation - Switching to Qwen...")
                try:
                    from app.services.translation.model_manager import load_model, unload_model
                    from app.config import settings
                    from app.services.translation.qwen_translator import translate_blocks_qwen
                    
                    # Unload Typhoon, Load Qwen
                    typhoon_model = "scb10x/typhoon-translate1.5-4b:latest"
                    qwen_model = settings.FALLBACK_MODEL
                    
                    unload_model(typhoon_model, settings.OLLAMA_URL)
                    load_model(qwen_model, settings.OLLAMA_URL)
                    
                    # Prepare failed texts
                    failed_texts = [chunk[idx] for idx in qwen_candidates_indices]
                    
                    # Translate
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
                    print(f"      ⚠️ Qwen Fallback Failed: {e}")

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
