"""
NLLB + Refine Translator Module
Handles two-step translation: NLLB Translation → LLM Refinement
"""
from typing import List, Dict, Tuple

from app.services.text_processor import normalize_text, should_translate
from app.services.llm_service import LLMService
from .nllb_service import nllb_translator
from .batch_translator import count_words, split_long_block, MAX_WORDS_PER_BLOCK, MAX_BLOCKS_PER_BATCH


class NLLBRefineTranslator:
    """
    Handles NLLB Translate + LLM Refine workflow
    """
    def __init__(self, llm_service: LLMService):
        self.llm = llm_service
        self.nllb = nllb_translator
        self.batch_size = MAX_BLOCKS_PER_BATCH
    
    def translate_and_refine(
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
        """
        แปลด้วย NLLB แล้วใช้ LLM Refine (Batch)
        1. NLLB Translate batch
        2. Unload NLLB model (free VRAM)
        3. LLM Refine batch
        """
        translated_blocks = []
        stats = {"total": 0, "translated": 0, "skipped": 0, "skipped_langs": {}}
        
        if not blocks:
            return translated_blocks, stats
        
        # แยก blocks ที่ต้องแปล vs ข้าม
        to_translate = []
        chunk_map = {}
        
        for idx, block in enumerate(blocks):
            text = normalize_text(block["text"])
            word_count = count_words(text)
            need, detected_lang = should_translate(text, target_lang)
            
            if need and text:
                if word_count > MAX_WORDS_PER_BLOCK:
                    print(f"   ⚠️ Block {idx+1} มีคำเกิน ({word_count} คำ) - กำลังแบ่ง...")
                    sub_chunks = split_long_block(text, max_words=MAX_WORDS_PER_BLOCK)
                    print(f"      → แบ่งเป็น {len(sub_chunks)} chunks")
                    
                    if idx not in chunk_map:
                        chunk_map[idx] = []
                    
                    for i, chunk in enumerate(sub_chunks):
                        to_translate.append((idx, block, chunk, detected_lang))
                        chunk_map[idx].append(len(to_translate) - 1)
                else:
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
        
        # แบ่งเป็น batches
        num_batches = (len(to_translate) + self.batch_size - 1) // self.batch_size
        print(f"   📊 NLLB+Refine: {len(to_translate)} items, {num_batches} batches (ละ {self.batch_size})")
        
        # Load NLLB model
        self.nllb.load_model()
        
        # เก็บผลลัพธ์ทั้งหมด
        all_nllb_results = []
        all_refined_results = []
        
        # Step 1: NLLB Translation
        print(f"   🌐 Step 1: NLLB Translation...")
        for batch_idx in range(num_batches):
            # ✅ Check cancelled flag before each NLLB batch
            if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
                print("   🚫 Job cancelled - stopping NLLB translation")
                return translated_blocks, stats
            
            start_idx = batch_idx * self.batch_size
            end_idx = min(start_idx + self.batch_size, len(to_translate))
            batch = to_translate[start_idx:end_idx]
            
            # Update progress
            if job_status and job_id:
                base_progress = 30 + int((page_no - 1) / total_pages * 50)
                batch_progress = base_progress + int((batch_idx / (num_batches * 2)) * 50 / total_pages)
                job_status[job_id]["progress"] = batch_progress
                job_status[job_id]["message"] = f"หน้า {page_no}/{total_pages}: NLLB Batch {batch_idx+1}/{num_batches}..."
            
            print(f"      🔄 NLLB Batch {batch_idx+1}/{num_batches} ({len(batch)} items)")
            
            # NLLB Translate
            batch_texts = [text for (_, _, text, _) in batch]
            # ✅ ใช้ source_lang จาก job แทนการ detect (ป้องกัน NLLB หลุด)
            src_lang = source_lang or "eng_Latn"
            
            nllb_results = self.nllb.translate_batch(
                batch_texts,
                src_lang=src_lang,
                tgt_lang=target_lang
            )
            all_nllb_results.extend(nllb_results)
        
        # Step 2: Unload NLLB (FREE VRAM!)
        print(f"   🗑️ Step 2: Unloading NLLB model...")
        self.nllb.unload_model()
        
        # Step 3: LLM Refine
        print(f"   ✨ Step 3: LLM Refine with {refine_model}...")
        
        # Temporarily switch model
        original_model = self.llm.model
        self.llm.model = refine_model
        
        for batch_idx in range(num_batches):
            # ✅ Check cancelled flag before each refine batch
            if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
                print("   🚫 Job cancelled - stopping LLM refine")
                # Return NLLB results (not refined) with stats
                self.llm.model = original_model
                # Build partial results from NLLB translations
                partial_blocks = []
                for j, (orig_idx, block, text, detected_lang) in enumerate(to_translate):
                    if j < len(all_nllb_results):
                        partial_blocks.append({
                            **block,
                            "original_text": block["text"],
                            "text": all_nllb_results[j],
                            "nllb_translated": all_nllb_results[j],
                            "detected_lang": detected_lang,
                            "was_translated": True
                        })
                # Merge with skipped blocks
                partial_blocks.extend(translated_blocks)
                return partial_blocks, stats
            
            start_idx = batch_idx * self.batch_size
            end_idx = min(start_idx + self.batch_size, len(to_translate))
            
            # Update progress
            if job_status and job_id:
                base_progress = 30 + int((page_no - 1) / total_pages * 50)
                batch_progress = base_progress + int(((num_batches + batch_idx) / (num_batches * 2)) * 50 / total_pages)
                job_status[job_id]["progress"] = batch_progress
                job_status[job_id]["message"] = f"หน้า {page_no}/{total_pages}: Refine Batch {batch_idx+1}/{num_batches}..."
            
            print(f"      ✨ Refine Batch {batch_idx+1}/{num_batches}")
            
            # Get NLLB results for this batch
            batch_nllb = all_nllb_results[start_idx:end_idx]
            
            # LLM Refine - select method based on model
            if "gemma" in refine_model.lower():
                refined_results = self.llm.refine_batch_gemma(batch_nllb, target_lang)
            elif "llama" in refine_model.lower():
                refined_results = self.llm.refine_batch_llama(batch_nllb, target_lang)
            else:  # qwen
                refined_results = self.llm.refine_batch_qwen(batch_nllb, target_lang)
            all_refined_results.extend(refined_results)
        
        # Restore model
        self.llm.model = original_model
        
        # Merge Results
        final_block_results = {}

        for j, (orig_idx, block, text, detected_lang) in enumerate(to_translate):
            nllb_trans = all_nllb_results[j] if j < len(all_nllb_results) else ""
            refined_trans = all_refined_results[j] if j < len(all_refined_results) else ""
            
            # Fallback logic
            final_trans = refined_trans if refined_trans.strip() else nllb_trans
            if not final_trans.strip():
                final_trans = text
            
            # Check if this is a chunk part
            if orig_idx in chunk_map:
                if orig_idx not in final_block_results:
                    final_block_results[orig_idx] = {"parts": [], "nllb_parts": [], "block": block, "lang": detected_lang}
                
                final_block_results[orig_idx]["parts"].append(final_trans)
                final_block_results[orig_idx]["nllb_parts"].append(nllb_trans)
            else:
                final_block_results[orig_idx] = {
                    "text": final_trans,
                    "nllb": nllb_trans,
                    "block": block,
                    "lang": detected_lang
                }
            
            stats["translated"] += 1

        # Construct final list
        all_results = [None] * len(blocks)
        
        # Fill skipped
        skip_idx = 0
        for idx, block in enumerate(blocks):
            text = normalize_text(block["text"])
            need, _ = should_translate(text, target_lang)
            if not need or not text:
                all_results[idx] = translated_blocks[skip_idx]
                skip_idx += 1
        
        # Fill translated
        for orig_idx, data in final_block_results.items():
            if "parts" in data:
                detected_lang = data["lang"]
                # สำหรับภาษาไทย ไม่ต้องเว้นวรรคเยอะ (อาจพิจารณา join ด้วย "" ถ้ามั่นใจ)
                # แต่เพื่อความปลอดภัย ใช้ " " ไปก่อน หรือเช็ค target_lang ก็ได้
                # ในที่นี้ให้ใช้ " " เหมือนเดิมไปก่อน แต่เตรียม logic ไว้
                join_char = " "
                
                final_text = join_char.join(data["parts"])
                final_nllb = join_char.join(data["nllb_parts"])
                block = data["block"]
                detected_lang = data["lang"]
            else:
                final_text = data["text"]
                final_nllb = data["nllb"]
                block = data["block"]
                detected_lang = data["lang"]
            
            all_results[orig_idx] = {
                **block,
                "original_text": block["text"],
                "text": final_text,
                "nllb_translated": final_nllb,
                "detected_lang": detected_lang,
                "was_translated": True
            }

        return [r for r in all_results if r is not None], stats
