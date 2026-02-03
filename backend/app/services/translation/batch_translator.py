"""
Batch Translator Module
Handles batch translation logic with retry and chunking
"""
import re
from typing import List, Dict, Tuple

from app.services.text_processor import normalize_text, should_translate
from app.services.llm_service import LLMService

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
        
        if not blocks:
            return translated_blocks, stats
        
        # 1. Prepare Tasks (Flatten all chunks)
        # Each item in all_tasks corresponds to a chunk of text
        all_tasks = [] 
        to_translate_indices = [] # Indices in all_tasks that need translation
        
        for idx, block in enumerate(blocks):
            text = normalize_text(block["text"])
            
            # แบ่งข้อความถ้าจำเป็น
            chunks = []
            word_count = count_words(text)
            if word_count > MAX_WORDS_PER_BLOCK:
                print(f"   ⚠️ Block {idx+1} มีคำเกิน ({word_count} คำ) - กำลังแบ่ง...")
                chunks = split_long_block(text, max_words=MAX_WORDS_PER_BLOCK)
                print(f"      → แบ่งเป็น {len(chunks)} chunks")
            else:
                chunks = [text]
            
            for chunk in chunks:
                if not chunk: continue
                
                need, detected_lang = should_translate(chunk, target_lang)
                
                task = {
                    'text': chunk,             # Content to translate (or keep)
                    'original_text': chunk,
                    'is_skipped': not need,
                    'detected_lang': detected_lang,
                    'original_idx': idx,       # Link back to original block
                    'result_text': chunk if not need else None # Pre-fill if skipped
                }
                
                all_tasks.append(task)
                
                if need:
                    to_translate_indices.append(len(all_tasks) - 1)
                else:
                    stats["skipped"] += 1
                    stats["skipped_langs"][detected_lang] = stats["skipped_langs"].get(detected_lang, 0) + 1

        stats["total"] = len(blocks)
        
        # 2. Batch Translation
        if to_translate_indices:
            # Extract texts to translate
            to_translate_texts = [all_tasks[i]['text'] for i in to_translate_indices]
            
            # Find source lang from first item (heuristic)
            first_task = all_tasks[to_translate_indices[0]]
            src_lang = first_task['detected_lang'] if first_task['detected_lang'] != "unknown" else "tha_Thai"
            
            num_batches = (len(to_translate_texts) + self.batch_size - 1) // self.batch_size
            print(f"   📊 ต้องแปล: {len(to_translate_texts)} chunks, ข้าม: {stats['skipped']}, batches: {num_batches}")
            
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
                
                # Execute Translation
                batch_results = self.llm.translate_batch_typhoon(batch_texts, target_lang, src_lang, job_status, job_id)
                
                # Verify results length
                if len(batch_results) != len(batch_texts):
                    print(f"   ⚠️ Mismatch results: got {len(batch_results)}, expected {len(batch_texts)}")
                    # Fill missing with empty string
                    batch_results.extend([""] * (len(batch_texts) - len(batch_results)))
                
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
