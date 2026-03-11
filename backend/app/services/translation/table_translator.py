"""
Table Translator Module
Handles table-specific translation logic for both PDF and Image tables
"""
import re
from typing import List, Dict

from app.services.text_processor import normalize_text, should_translate, detect_language
from app.services.llm_service import LLMService
from app.services.translation.table_validator import (
    _CJK_LANGS,
    _get_source_leakage_scripts,
    validate_translation,
    check_cjk_presence,
)
from app.services.translation.table_html_parser import HTMLTableParser
from app.services.translation.table_fallback import (
    run_qwen_cell_fallback,
    run_qwen_raw_fallback,
    rebuild_html_table,
)

TABLE_CELLS_PER_BATCH = 6  # จำนวน cells สูงสุดต่อ batch


class TableTranslator:
    """
    Handles table cell translation with batch support (Typhoon Only)
    Supports both PDF tables (structured cells) and Image tables (HTML blocks)
    """
    def __init__(self, llm_service: LLMService):
        self.llm = llm_service

    # ------------------------------------------------------------------
    # Public API — Image / HTML tables
    # ------------------------------------------------------------------

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

        translated_parts = []
        for part in parts:
            if not part.strip():
                translated_parts.append(part)
                continue

            if '<table>' in part.lower() and '</table>' in part.lower():
                translated_parts.append(self._translate_table_cells(part, target_lang, src_lang))
            else:
                translated_parts.append(self._translate_text(part, target_lang, src_lang))

        return ''.join(translated_parts)

    def translate_ocr_table_block(
        self,
        text: str,
        target_lang: str,
        src_lang: str = "tha_Thai"
    ) -> str:
        """
        Translate raw OCR text (Markdown/Plain) => HTML Table
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
            "4. Output ONLY the HTML code. No markdown code blocks.\n"
            "5. Stop translating exactly where the original text ends. Do not add any sentences.\n\n"
            f"Input:\n{text}\n\n"
            "Output (HTML Table):"
        )

        translated_html = ""
        try:
            translated_html = self.llm.generate(prompt, temperature=0.1, max_tokens=2048)
            match = re.search(r'<table>.*?</table>', translated_html, re.DOTALL | re.IGNORECASE)
            if match:
                translated_html = match.group(0)
            elif '<tr>' in translated_html:
                translated_html = f"<table>{translated_html}</table>"
        except Exception as e:
            print(f"      ⚠️ Typhoon Table Error: {e}")
            translated_html = ""

        # 2. Validate
        is_valid = bool(translated_html and len(translated_html) >= 10)
        if not is_valid:
            print("      ❌ Table Validation Failed: Empty result")

        if is_valid and not check_cjk_presence(translated_html, target_lang):
            is_valid = False
            print(f"      ❌ Table Validation Failed: No {target_lang} characters found in output")

        # 3. Fallback to Qwen if invalid
        if not is_valid:
            print("      🔄 Switching to Qwen for Table Translation...")
            qwen_prompt = (
                f"Translate this table from {src_lang} to {target_lang}. \n"
                "Output ONLY the HTML <table> structure. \n"
                "Ensure all cell contents are translated.\n"
                "Stop translating exactly where the original text ends. Do not add any sentences.\n\n"
                f"{text}"
            )
            qwen_html = run_qwen_raw_fallback(qwen_prompt)

            match = re.search(r'<table>.*?</table>', qwen_html, re.DOTALL | re.IGNORECASE)
            if match:
                translated_html = match.group(0)
            elif '<tr>' in qwen_html:
                translated_html = f"<table>{qwen_html}</table>"
            elif qwen_html:
                translated_html = qwen_html  # Best effort
            else:
                if not translated_html:
                    return text

            print("      ✅ Qwen Table Translation Completed")

        return translated_html

    # ------------------------------------------------------------------
    # Public API — PDF tables
    # ------------------------------------------------------------------

    def translate_cells(
        self,
        cells: List[Dict],
        target_lang: str,
        use_nllb_refine: bool = False,
        refine_model: str = None
    ) -> List[Dict]:
        """แปล cells ในตาราง PDF (Typhoon Direct)"""
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

        texts = [c['original_text'] for c in to_translate]
        src_lang = to_translate[0]['detected_lang'] if to_translate else 'tha_Thai'
        chunk_size = TABLE_CELLS_PER_BATCH
        total_batches = (len(texts) + chunk_size - 1) // chunk_size

        print(f"   📊 PDF Table: {len(texts)} cells, {total_batches} batches (ละ {chunk_size})")

        translated_texts = []
        for i in range(0, len(texts), chunk_size):
            chunk = texts[i:i + chunk_size]
            batch_num = (i // chunk_size) + 1
            total_batches = (len(texts) + chunk_size - 1) // chunk_size
            print(f"   🔄 Batch {batch_num}/{total_batches}: cells {i+1}-{i+len(chunk)}")

            chunk_results, failed_indices = self.llm.translate_batch_typhoon(chunk, target_lang, src_lang)

            validated_results, qwen_indices = self._validate_chunk(
                chunk, chunk_results, failed_indices, src_lang, target_lang, offset=i
            )

            if qwen_indices:
                print(f"      🚨 {len(qwen_indices)} cells failed validation - Switching to Qwen...")
                failed_texts = [chunk[idx] for idx in qwen_indices]
                qwen_results = run_qwen_cell_fallback(failed_texts, target_lang, src_lang)

                for q_idx, original_idx in enumerate(qwen_indices):
                    if qwen_results[q_idx] and qwen_results[q_idx] != failed_texts[q_idx]:
                        validated_results[original_idx] = qwen_results[q_idx]
                        print(f"      ✅ Cell {i+original_idx+1} recovered by Qwen")
                    else:
                        print(f"      ❌ Cell {i+original_idx+1} failed even with Qwen")

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
            translated_cells = self.translate_cells(cells, target_lang)

            translated_tables.append({**table, 'cells': translated_cells})

            if translated_cells:
                print(f"      📊 Table {table.get('num_rows', 0)}x{table.get('num_cols', 0)}: {len(translated_cells)} cells translated")

        return translated_tables

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_chunk(
        self,
        chunk: List[str],
        chunk_results: List[str],
        failed_indices: List[int],
        src_lang: str,
        target_lang: str,
        offset: int = 0
    ):
        """
        Validate a batch of translated cells.
        Returns (validated_results, qwen_candidates_indices).
        """
        validated_results = []
        qwen_candidates_indices = []

        for idx, (original, translated) in enumerate(zip(chunk, chunk_results)):
            is_failed = (idx in failed_indices)

            if not is_failed:
                is_failed = not validate_translation(
                    original, translated, src_lang, target_lang,
                    cell_num=offset + idx + 1
                )

            if is_failed:
                qwen_candidates_indices.append(idx)
                validated_results.append(original)  # Placeholder until Qwen runs
            else:
                validated_results.append(translated)

        return validated_results, qwen_candidates_indices

    def _translate_table_cells(
        self,
        table_html: str,
        target_lang: str,
        src_lang: str
    ) -> str:
        """แปล cells ภายใน HTML table"""
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
        print(f"      📝 Sample cells: {cells[:3]}")

        # Auto-detect source language
        if src_lang == "auto":
            src_lang = self._detect_table_lang(cells)

        # Translate in batches
        translated_cells = []
        chunk_size = TABLE_CELLS_PER_BATCH

        for i in range(0, len(cells), chunk_size):
            chunk = cells[i:i + chunk_size]
            batch_num = (i // chunk_size) + 1
            total_batches = (len(cells) + chunk_size - 1) // chunk_size
            print(f"   🔄 Batch {batch_num}/{total_batches}: cells {i+1}-{i+len(chunk)}")

            chunk_results, failed_indices = self.llm.translate_batch_typhoon(chunk, target_lang, src_lang)
            print(f"      📝 Translated: {chunk_results}")

            validated_results, qwen_indices = self._validate_chunk(
                chunk, chunk_results, failed_indices, src_lang, target_lang, offset=i
            )

            if qwen_indices:
                print(f"      🚨 {len(qwen_indices)} cells failed validation - Switching to Qwen...")
                failed_texts = [chunk[idx] for idx in qwen_indices]
                qwen_results = run_qwen_cell_fallback(failed_texts, target_lang, src_lang)

                for q_idx, original_idx in enumerate(qwen_indices):
                    if qwen_results[q_idx] and qwen_results[q_idx] != failed_texts[q_idx]:
                        validated_results[original_idx] = qwen_results[q_idx]
                        print(f"      ✅ Cell {i+original_idx+1} recovered by Qwen")
                    else:
                        print(f"      ❌ Cell {i+original_idx+1} failed even with Qwen")

            translated_cells.extend(validated_results)

        rebuilt = rebuild_html_table(table_html, cells, translated_cells)
        print(f"      ✅ HTML Table: Translated {len(translated_cells)}/{len(cells)} cells")
        return rebuilt

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

        if src_lang == "auto":
            detected = detect_language(text)
            if detected in ["unknown", "eng_Latn"] and len(text) > 20:
                has_cjk_thai = any('\u0e00' <= c <= '\u0e7f' or
                                   '\u3040' <= c <= '\u30ff' or
                                   '\u4e00' <= c <= '\u9fff' or
                                   '\uac00' <= c <= '\ud7af'
                                   for c in text)
                if not has_cjk_thai:
                    print("      🔍 Text language ambiguous, checking LLM...")
                    detected = self.llm.detect_language(text[:500])
            src_lang = detected
            print(f"      🤖 Text Language Detected: {src_lang}")

        results, failed_indices = self.llm.translate_batch_typhoon([text], target_lang, src_lang)

        needs_fallback = bool(failed_indices) or not results or not results[0]
        if needs_fallback:
            print("      🚨 Text validation failed/rejected - Switching to Qwen...")
            qwen_results = run_qwen_cell_fallback([text], target_lang, src_lang)
            if qwen_results and qwen_results[0] and qwen_results[0] != text:
                print("      ✅ Text recovered by Qwen")
                return qwen_results[0]

        if results and results[0]:
            if failed_indices:
                print(f"      ⚠️ Text validation failed but keeping translation attempt")
            return results[0]

        print(f"      ⚠️ Text translation produced no result, keeping original")
        return text

    def _detect_table_lang(self, cells: List[str]) -> str:
        """Auto-detect source language from table cell content."""
        sample_text = " ".join(cells[:20])
        detected = detect_language(sample_text)

        if detected in ["unknown", "eng_Latn"]:
            has_cjk_thai = any('\u0e00' <= c <= '\u0e7f' or
                               '\u3040' <= c <= '\u30ff' or
                               '\u4e00' <= c <= '\u9fff' or
                               '\uac00' <= c <= '\ud7af'
                               for c in sample_text)
            if not has_cjk_thai and len(sample_text) > 20:
                print("      🔍 Table language ambiguous, checking LLM...")
                detected = self.llm.detect_language(sample_text[:500])

        if detected == "unknown":
            if any('\u0e00' <= c <= '\u0e7f' for c in sample_text):
                detected = "tha_Thai"
            elif any('\uac00' <= c <= '\ud7af' for c in sample_text):
                detected = "kor_Hang"
            elif any('\u3040' <= c <= '\u30ff' for c in sample_text):
                detected = "jpn_Jpan"
            elif any('\u4e00' <= c <= '\u9fff' for c in sample_text):
                detected = "zho_Hans"
            else:
                detected = "eng_Latn"
            print(f"      ⚠️ Defaulting unknown source -> {detected}")

        print(f"      🤖 Table Language Detected: {detected}")
        return detected
