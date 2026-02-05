"""
Batch Translator Module
Handles batch translation logic with retry and chunking
"""
import re
from typing import List, Dict, Tuple

from app.services.text_processor import normalize_text, should_translate
from app.services.llm_service import LLMService
from app.config import settings
from app.services.translation.qwen_translator import translate_blocks_qwen
from app.services.translation.model_manager import unload_model, load_model, preload_model

# Batch Size Constants
MAX_WORDS_PER_BLOCK = 200      # ✅ เพิ่มจาก 70 → 200 เพราะ NLLB รับได้ 1024 tokens แล้ว
MAX_BLOCKS_PER_BATCH = 3       # จำนวน blocks สูงสุดต่อ batch (ตรงกับ config)


def count_words(text: str) -> int:
    """นับจำนวนคำ รวม marker ###BLOCKn### ด้วย"""
    words = re.findall(r'\S+|\s+', text)
    return len(words)


def split_long_block(text: str, max_words: int = MAX_WORDS_PER_BLOCK) -> List[str]:
    """
    แบ่งข้อความที่มีคำเกิน max_words เป็น chunks เล็กๆ
    - แบ่งตามประโยค (. ! ?)
    - สำหรับภาษาไทย แบ่งตามเว้นวรรค
    """
    word_count = count_words(text)
    
    if word_count <= max_words:
        return [text]
    
    chunks = []
    
    # แบ่งตามประโยค (รองรับ Eng และ Thai spaces)
    # 1. Split by sentence endings (.!?) followed by space
    # 2. Or split by double spaces (common in PDF extractions)
    # 3. Or split by newline
    sentences = re.split(r'(?<=[.!?])\s+|(?<=\s\s)|\n+', text)
    
    current_chunk = ""
    current_word_count = 0
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

            
        sentence_words = count_words(sentence)
        
        if current_word_count + sentence_words <= max_words:
            current_chunk += sentence + " "
            current_word_count += sentence_words
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
            current_word_count = sentence_words
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    # ถ้าแบ่งไม่ได้ (ประโยคเดียวยาวกว่า limit) → ตัดตามคำ
    final_chunks = []
    for chunk in chunks:
        if count_words(chunk) > max_words:
            words = chunk.split()
            temp_chunk = ""
            for word in words:
                if count_words(temp_chunk + " " + word) <= max_words:
                    temp_chunk += word + " "
                else:
                    if temp_chunk:
                        final_chunks.append(temp_chunk.strip())
                    temp_chunk = word + " "
            if temp_chunk:
                final_chunks.append(temp_chunk.strip())
        else:
            final_chunks.append(chunk)
    
    return [c for c in final_chunks if c.strip()]


class BatchTranslator:
    """
    Handles batch translation with retry logic and chunking
    """
    def __init__(self, llm_service: LLMService, batch_size: int = MAX_BLOCKS_PER_BATCH):
        self.llm = llm_service
        self.batch_size = batch_size
        self.max_retries = 2
    
    def translate_blocks(
        self, 
        blocks: List[Dict], 
        target_lang: str,
        source_lang: str = "eng_Latn",  # Add source_lang parameter
        job_status: dict = None,
        job_id: str = None
    ) -> Tuple[List[Dict], Dict]:
        """
        แปล text blocks ทั้งหมด
        - แบ่งเป็น batches
        - รองรับการ split block แล้วบางส่วนไม่ต้องแปล (Mixed content)
        - Returns: (translated_blocks, stats)
        """
        translated_blocks = []
        stats = {"total": 0, "translated": 0, "skipped": 0, "skipped_langs": {}}
        original_model = self.llm.model # Capture original model for restoration
        
        if not blocks:
            return translated_blocks, stats
        
        # 1. Prepare Tasks (Flatten all chunks)
        # Each item in all_tasks corresponds to a chunk of text
        all_tasks = [] 
        to_translate_indices = [] # Indices in all_tasks that need translation
        lang_stats = {}  # Track detected languages {lang: count}
        
        # Collect all text chunks that need translation
        for idx, block in enumerate(blocks):
            text = block.get('text', '')
            if not text:
                continue
            
            # Split long blocks to avoid context overflow
            if (isinstance(text, str) and len(text) > MAX_WORDS_PER_BLOCK * 10 
                and '<table>' not in text.lower()):  # Don't split tables
                chunks = split_long_block(text, max_words=MAX_WORDS_PER_BLOCK)
                print(f"      → แบ่งเป็น {len(chunks)} chunks")
            else:
                chunks = [text]
            
            for chunk in chunks:
                if not chunk: continue
                
                #  Check if chunk contains HTML table
                has_html_table = '<table>' in chunk.lower() and '</table>' in chunk.lower()
                
                # Per-block hybrid detection
                need, detected_lang = should_translate(chunk, target_lang)
                
                # If in auto mode and detected as unknown/eng_Latn (ambiguous), use LLM for accuracy
                if source_lang == "auto" and detected_lang in ["unknown", "eng_Latn"]:
                    # Check if rule-based was certain (has CJK/Thai characters)
                    has_cjk_thai = any('\u0e00' <= c <= '\u0e7f' or  # Thai
                                       '\u3040' <= c <= '\u30ff' or  # Japanese
                                       '\u4e00' <= c <= '\u9fff' or  # Chinese
                                       '\uac00' <= c <= '\ud7af'     # Korean
                                       for c in chunk)
                    
                    if not has_cjk_thai and len(chunk.strip()) > 20:
                        # Likely other language (Russian, Arabic, etc) - use LLM
                        detected_lang = self.llm.detect_language(chunk)
                        # Re-check need based on new detected_lang
                        if detected_lang == target_lang:
                            need = False
                        else:
                            need = True
                
                # Track language stats
                lang_stats[detected_lang] = lang_stats.get(detected_lang, 0) + 1
                
                task = {
                    'text': chunk,             # Content to translate (or keep)
                    'original_text': chunk,
                    'is_skipped': not need,
                    'detected_lang': detected_lang,
                    'original_idx': idx,       # Link back to original block
                    'result_text': chunk if not need else None,  # Pre-fill if skipped
                    'has_html_table': has_html_table  # Flag for special handling
                }
                
                all_tasks.append(task)
                
                if need:
                    to_translate_indices.append(len(all_tasks) - 1)
                else:
                    stats["skipped"] += 1
                    stats["skipped_langs"][detected_lang] = stats["skipped_langs"].get(detected_lang, 0) + 1

        stats["total"] = len(blocks)
        
        # Log detected languages summary
        if lang_stats and source_lang == "auto":
            lang_summary = ", ".join([f"{lang} ({count})" for lang, count in sorted(lang_stats.items(), key=lambda x: -x[1])])
            print(f"   📊 Detected Languages: {lang_summary}")
        
        # 2. Handle HTML Tables separately (from images)
        html_table_indices = []
        regular_translate_indices = []
        
        for idx in to_translate_indices:
            if all_tasks[idx].get('has_html_table', False):
                html_table_indices.append(idx)
            else:
                regular_translate_indices.append(idx)
        
        # Translate HTML tables using TableTranslator
        if html_table_indices:
            from .table_translator import TableTranslator
            table_translator = TableTranslator(self.llm)
            
            print(f"   📊 HTML Tables: {len(html_table_indices)} blocks detected")
            
            # Use global source_lang instead of per-block detection
            for idx in html_table_indices:
                task = all_tasks[idx]
                translated_html = table_translator.translate_html_table_block(
                    task['text'],
                    target_lang,
                    source_lang  # Use global source_lang
                )
                task['result_text'] = translated_html
                stats["translated"] += 1
        
        # Update regular translation list
        to_translate_indices = regular_translate_indices
        
        # 3. Batch Translation (Regular blocks)
        if to_translate_indices:
            # Extract texts to translate
            to_translate_texts = [all_tasks[i]['text'] for i in to_translate_indices]
            
            # Use most common detected language as src_lang for batch
            detected_langs = [all_tasks[i]['detected_lang'] for i in to_translate_indices]
            from collections import Counter
            lang_counter = Counter(detected_langs)
            src_lang = lang_counter.most_common(1)[0][0] if lang_counter else "eng_Latn"
            if src_lang == "unknown":
                src_lang = "eng_Latn"
            
            num_batches = (len(to_translate_texts) + self.batch_size - 1) // self.batch_size
            print(f"   📊 ต้องแปล: {len(to_translate_texts)} chunks, ข้าม: {stats['skipped']}, batches: {num_batches}")
            if source_lang == "auto":
                print(f"      🔤 Using {src_lang} for batch translation")
            
            current_translate_idx = 0
            
            for batch_idx in range(num_batches):
                # Check Cancel
                if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
                    print("   🚫 Job cancelled - stopping batch translation")
                    return [], stats # Caller handles empty return
                
                start = batch_idx * self.batch_size
                end = min(start + self.batch_size, len(to_translate_texts))
                batch_texts = to_translate_texts[start:end]
                
                print(f"   🔄 Batch {batch_idx + 1}/{num_batches} ({len(batch_texts)} chunks)")
                
                # Execute Translation (Typhoon) - First Attempt
                # Returns (results, failed_validation_indices)
                batch_results, batch_failed_indices = self.llm.translate_batch_typhoon(
                    batch_texts, target_lang, src_lang, job_status, job_id
                )
                
                # Verify results length
                if len(batch_results) != len(batch_texts):
                    print(f"   ⚠️ Mismatch results: got {len(batch_results)}, expected {len(batch_texts)}")
                    batch_results.extend([""] * (len(batch_texts) - len(batch_results)))
                
                # --- Step 1: Retry Failed Blocks with Typhoon ---
                if batch_failed_indices:
                    failed_texts = [batch_texts[i] for i in batch_failed_indices]
                    print(f"   🔄 Retry {len(failed_texts)} failed blocks with Typhoon...")
                    
                    retry_results, still_failed_indices = self.llm.translate_batch_typhoon(
                        failed_texts, target_lang, src_lang, job_status, job_id
                    )
                    
                    # Merge retry results
                    successfully_recovered = []
                    for idx, fail_idx in enumerate(batch_failed_indices):
                        if idx not in still_failed_indices and retry_results[idx]:
                            batch_results[fail_idx] = retry_results[idx]
                            successfully_recovered.append(fail_idx)
                    
                    if successfully_recovered:
                        print(f"      ✅ Typhoon retry recovered {len(successfully_recovered)} blocks")
                    
                    # Recalculate final failed indices (those still failed after retry)
                    final_failed_indices = [batch_failed_indices[i] for i in still_failed_indices]
                    
                    # --- Step 2: Qwen Fallback for Still-Failed Blocks ---
                    if final_failed_indices:
                        print(f"   🚨 {len(final_failed_indices)} blocks still failed - Switching to Qwen...")
                        
                        # Unload Typhoon
                        typhoon_model = "scb10x/typhoon-translate1.5-4b:latest"
                        unload_model(typhoon_model, settings.OLLAMA_URL)
                        
                        # Load Qwen
                        qwen_model = "qwen2.5:3b"
                        load_model(qwen_model, settings.OLLAMA_URL)
                        
                        # Translate with Qwen
                        qwen_texts = [batch_texts[i] for i in final_failed_indices]
                        qwen_results, qwen_failed = translate_blocks_qwen(
                            qwen_texts, target_lang, src_lang, settings.OLLAMA_URL, qwen_model, job_status, job_id
                        )
                        
                        # Merge Qwen results
                        for idx, fail_idx in enumerate(final_failed_indices):
                            if qwen_results[idx]:
                                batch_results[fail_idx] = qwen_results[idx]
                                print(f"      ✅ Block {fail_idx+1} recovered by Qwen")
                            else:
                                print(f"      ❌ Block {fail_idx+1} failed even with Qwen")
                        
                        # Cleanup: Unload Qwen, Preload Typhoon
                        unload_model(qwen_model, settings.OLLAMA_URL)
                        preload_model(typhoon_model, settings.OLLAMA_URL)

                
                # Assign results back to tasks
                for res_text in batch_results:
                    task_idx = to_translate_indices[current_translate_idx]
                    
                    # Log failure if empty and not skipped
                    if not res_text.strip():
                        print(f"      ⚠️ Chunk translation failed, using original")
                        res_text = all_tasks[task_idx]['original_text']
                    
                    all_tasks[task_idx]['result_text'] = res_text
                    current_translate_idx += 1
                    stats["translated"] += 1
        
        # 3. Reconstruct Blocks
        # Group tasks by original_idx
        from collections import defaultdict
        block_parts = defaultdict(list)
        
        for task in all_tasks:
            block_parts[task['original_idx']].append(task['result_text'])
            
        final_results = []
        for idx, block in enumerate(blocks):
            if idx in block_parts:
                parts = block_parts[idx]
                
                # Join parts
                # Try to preserve original separator if possible
                original_text = block["text"]
                if "\n\n" in original_text: joiner = "\n\n"
                elif "\n" in original_text: joiner = "\n"
                else: joiner = " "
                
                final_text = joiner.join(parts)
                
                final_results.append({
                    **block,
                    "original_text": block["text"],
                    "text": final_text,
                    "detected_lang": block.get("detected_lang", "unknown"), # Use original detected or mixed?
                    "was_translated": True
                })
            else:
                # Caso weird: block had no text/chunks? Just append as is
                final_results.append({
                    **block,
                    "original_text": block["text"],
                    "text": block["text"],
                    "was_translated": False
                })
                
        return final_results, stats
