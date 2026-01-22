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
MAX_BLOCKS_PER_BATCH = 5       # จำนวน blocks สูงสุดต่อ batch


def count_words(text: str) -> int:
    """นับจำนวนคำ รวม marker ###BLOCKn### ด้วย"""
    words = text.split()
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
        - Simple retry logic
        - Returns: (translated_blocks, stats)
        """
        translated_blocks = []
        stats = {"total": 0, "translated": 0, "skipped": 0, "skipped_langs": {}}
        
        if not blocks:
            return translated_blocks, stats
        
        # แยก blocks ที่ต้องแปล vs ข้าม
        to_translate = []
        chunk_map = {}  # Track split chunks: { orig_idx: [to_translate_idx, ...] }
        
        for idx, block in enumerate(blocks):
            text = normalize_text(block["text"])
            
            # ตรวจสอบจำนวนคำ - แบ่ง block ถ้าเกิน MAX_WORDS_PER_BLOCK
            word_count = count_words(text)
            if word_count > MAX_WORDS_PER_BLOCK:
                print(f"   ⚠️ Block {idx+1} มีคำเกิน ({word_count} คำ) - กำลังแบ่ง...")
                sub_chunks = split_long_block(text, max_words=MAX_WORDS_PER_BLOCK)
                print(f"      → แบ่งเป็น {len(sub_chunks)} chunks")
                
                if idx not in chunk_map:
                    chunk_map[idx] = []
                    
                for i, chunk in enumerate(sub_chunks):
                    new_block = {
                        **block,
                        "text": chunk,
                        "original_text": chunk
                    }
                    need, detected_lang = should_translate(chunk, target_lang)
                    
                    if need and chunk:
                        to_translate.append((idx, new_block, chunk, detected_lang))
                        chunk_map[idx].append(len(to_translate) - 1)
                    else:
                        translated_blocks.append({
                            **new_block,
                            "detected_lang": detected_lang,
                            "was_translated": False
                        })
                        stats["skipped"] += 1
                        stats["skipped_langs"][detected_lang] = stats["skipped_langs"].get(detected_lang, 0) + 1
            else:
                # Block ปกติ - เช็คว่าต้องแปลไหม
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
                    stats["skipped_langs"][detected_lang] = stats["skipped_langs"].get(detected_lang, 0) + 1
        
        stats["total"] = len(blocks)
        
        if not to_translate:
            return translated_blocks, stats
        
        # หา source language
        src_lang = to_translate[0][3] if to_translate[0][3] != "unknown" else "tha_Thai"
        
        # แบ่งเป็น batches
        num_batches = (len(to_translate) + self.batch_size - 1) // self.batch_size
        print(f"   📊 ต้องแปล: {len(to_translate)}, ข้าม: {stats['skipped']}, batches: {num_batches} (ละ {self.batch_size} blocks)")
        
        # สร้าง temp results
        temp_results = [None] * len(to_translate)
        
        for batch_idx in range(num_batches):
            # ✅ Check cancelled flag before each batch
            if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
                print("   🚫 Job cancelled - stopping batch translation")
                # Return what we have so far
                return [r for r in all_results if r is not None], stats
            
            start_idx = batch_idx * self.batch_size
            end_idx = min(start_idx + self.batch_size, len(to_translate))
            batch = to_translate[start_idx:end_idx]
            
            print(f"   🔄 Batch {batch_idx + 1}/{num_batches} ({len(batch)} blocks)")
            
            batch_texts = [text for (_, _, text, _) in batch]
            batch_results = self.llm.translate_batch_llm(batch_texts, target_lang, src_lang)
            
            # Fallback: ถ้า batch failed → แปลทีละ block
            if not any(batch_results) and batch_texts:
                print(f"   ⚠️ Batch failed for {len(batch)} blocks. Switching to single mode...")
                batch_results = []
                for text in batch_texts:
                    res = self.llm.translate_text(text, target_lang)
                    batch_results.append(res)

            # Process results
            for j, (orig_idx, block, text, detected_lang) in enumerate(batch):
                # text = normalized OCR text  to translate
                # block["text"] = original un-normalized OCR text
                
                paragraphs = text.split("\n\n")
                
                # Fallback split ถ้าไม่มี \n\n
                if len(paragraphs) <= 1 and len(text) > 200 and "\n" in text:
                    paragraphs = [p for p in text.split("\n") if p.strip()]
                
                translated = ""
                
                if len(paragraphs) > 1:
                    # หลายย่อหน้า: แปลแยก
                    print(f"      📄 Block {orig_idx+1}: Force splitting {len(paragraphs)} paragraphs...")
                    translated_paragraphs = []
                    for para in paragraphs:
                        if para.strip():
                            trans_para = self.llm.translate_text(para.strip(), target_lang)
                            translated_paragraphs.append(trans_para if trans_para.strip() else para)
                        else:
                            translated_paragraphs.append("")
                    
                    join_char = "\n\n" if "\n\n" in text else "\n"
                    translated = join_char.join(translated_paragraphs)
                else:
                    # ย่อหน้าเดียว: ใช้ผล batch
                    translated = batch_results[j] if j < len(batch_results) and batch_results[j] else ""
                    
                    # Fallback Level 1: Retry
                    if not translated.strip():
                        translated = self.llm.translate_text(text, target_lang)
                    
                    # Fallback Level 2: Secondary model
                    if not translated.strip():
                        secondary_model = "gemma2:2b" if "qwen" in self.llm.model.lower() else "qwen2.5:3b"
                        print(f"      🔄 Block {orig_idx+1}: Trying secondary model ({secondary_model})...")
                        
                        original_model = self.llm.model
                        self.llm.model = secondary_model
                        translated = self.llm.translate_text(text, target_lang)
                        self.llm.model = original_model
                
                # Final fallback: Use original
                if not translated.strip():
                   print(f"      ⚠️ Block {orig_idx+1}: All fallbacks failed, using original text")
                   translated = text
                
                # CRITICAL FIX: Use the original text from the tuple, not block["text"]
                temp_results[start_idx + j] = {
                    **block,
                    "original_text": text,  # ✅ Use normalized text as original for logging
                    "text": translated,
                    "detected_lang": detected_lang,
                    "was_translated": True
                }
                stats["translated"] += 1
        
        # รวมผลลัพธ์
        all_results = [None] * len(blocks)
        
        # ใส่ blocks ที่ข้าม
        skip_idx = 0
        for idx, block in enumerate(blocks):
            text = normalize_text(block["text"])
            need, _ = should_translate(text, target_lang)
            if not need or not text:
                all_results[idx] = translated_blocks[skip_idx]
                skip_idx += 1
        
        # ใส่ blocks ที่แปล (Merged)
        final_block_results = {}
        for j, (orig_idx, block, text, detected_lang) in enumerate(to_translate):
            res = temp_results[j]
            final_trans = res["text"]
            
            if orig_idx in chunk_map:
                if orig_idx not in final_block_results:
                     final_block_results[orig_idx] = {"parts": [], "block": block} 
                final_block_results[orig_idx]["parts"].append(final_trans)
            else:
                 final_block_results[orig_idx] = {"text": final_trans, "block": block}
        
        for orig_idx, data in final_block_results.items():
            block = blocks[orig_idx]  # Get original block
            
            if "parts" in data:
                # Merged chunks - ✅ รักษา separator เดิมแทนการใช้ space
                original_text = blocks[orig_idx]["text"]
                # ตรวจสอบว่ามี paragraph separator หรือไม่
                if "\n\n" in original_text:
                    final_text = "\n\n".join(data["parts"])
                elif "\n" in original_text:
                    final_text = "\n".join(data["parts"])
                else:
                    final_text = " ".join(data["parts"])
                
                all_results[orig_idx] = {
                    **block,
                    "original_text": block["text"],  # ✅ Original OCR text
                    "text": final_text,
                    "detected_lang": block.get("detected_lang", "unknown"),
                    "was_translated": True
                }
            else:
                # Single block
                all_results[orig_idx] = {
                    **data["block"],
                    "original_text": block["text"],  # ✅ Original OCR text
                    "text": data["text"],
                    "detected_lang": data["block"].get("detected_lang", "unknown"),
                    "was_translated": True
                }
        
        return [r for r in all_results if r is not None], stats
