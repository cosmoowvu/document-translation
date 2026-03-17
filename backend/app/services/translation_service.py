
import re
# Import from new translation modules
from app.services.translation import translation_service


def _run_qwen3_final_pass(
    doc_result: dict,
    source_lang: str,
    target_lang: str,
    job_status: dict,
    job_id: str,
    ollama_url: str
):
    """
    Final pass: scan ALL translated blocks for remaining source language leakage.
    Covers two cases:
      A) source is CJK → check if CJK chars still appear in (non-CJK target) output
      B) target is CJK → check if source chars (non-English) still appear in CJK output
    Blocks with >5% source leakage are re-translated with qwen3:1.7b.
    After done: unload qwen3:1.7b and preload Typhoon.
    """
    from app.services.translation.qwen_translator import translate_blocks_qwen
    from app.services.translation.model_manager import unload_model, preload_model, load_model

    TYPHOON_MODEL = "scb10x/typhoon-translate1.5-4b:latest"
    QWEN3_MODEL = "qwen3:1.7b"

    CJK_LANGS = {"jpn_Jpan", "ja", "zho_Hans", "zho_Hant", "zh", "zh-cn", "kor_Hang", "ko"}

    # Unicode character ranges for each language group
    LANG_RANGES = {
        "jpn_Jpan":  [('\u3040', '\u30ff'), ('\u4e00', '\u9fff')],  # Kana + Kanji
        "ja":        [('\u3040', '\u30ff'), ('\u4e00', '\u9fff')],
        "zho_Hans":  [('\u4e00', '\u9fff')],
        "zho_Hant":  [('\u4e00', '\u9fff')],
        "zh":        [('\u4e00', '\u9fff')],
        "zh-cn":     [('\u4e00', '\u9fff')],
        "kor_Hang":  [('\uac00', '\ud7af')],
        "ko":        [('\uac00', '\ud7af')],
        "tha_Thai":  [('\u0e00', '\u0e7f')],
        "lao_Laoo":  [('\u0e80', '\u0eff')],
        "khm_Khmr":  [('\u1780', '\u17ff')],
        "mya_Mymr":  [('\u1000', '\u109f')],
        "ara_Arab":  [('\u0600', '\u06ff')],
    }
    # English (Latin) is intentionally NOT in LANG_RANGES → allowed to pass through

    def _get_leakage_ranges(lang: str):
        """Return unicode ranges for the given language. Returns [] if English or unknown."""
        return LANG_RANGES.get(lang, [])

    def _has_source_leakage(text: str, lang_to_check: str) -> bool:
        """Return True if >5% of text consists of `lang_to_check` characters."""
        if not text:
            return False
        ranges = _get_leakage_ranges(lang_to_check)
        if not ranges:
            return False  # English or unknown → no leakage concern
        # Strip HTML tags so <td>, <tr> etc. don't dilute the ratio
        clean = re.sub(r'<[^>]+>', '', text)
        total = len(clean)
        if total == 0:
            return False
        src_count = sum(1 for c in clean if any(s <= c <= e for s, e in ranges))
        return (src_count / total) > 0.05

    target_is_cjk = target_lang in CJK_LANGS
    source_is_cjk = source_lang in CJK_LANGS

    # Collect problem blocks across all pages
    problem_blocks = []  # list of (page_key, block_idx, block, src_lang_for_block)
    for page_key, page_data in doc_result.get("pages", {}).items():
        for block_idx, block in enumerate(page_data.get("blocks", [])):
            text = block.get("text", "")
            detected_lang = block.get("detected_lang", source_lang)
            if detected_lang in ("unknown", ""):
                detected_lang = source_lang

            has_leakage = False

            if source_is_cjk or (source_lang == "auto" and detected_lang in CJK_LANGS):
                # Case A: source was CJK → check if CJK still in output
                check_lang = detected_lang if detected_lang in CJK_LANGS else source_lang
                has_leakage = _has_source_leakage(text, check_lang)

            if target_is_cjk and not has_leakage:
                # Case B: target is CJK → check if source language (non-English) leaked
                # Use detected_lang of the block as the "source to check for"
                has_leakage = _has_source_leakage(text, detected_lang)

            if has_leakage:
                problem_blocks.append((page_key, block_idx, block, detected_lang))

    if not problem_blocks:
        print("   ✅ Qwen3 Final Pass: No leakage detected — all blocks clean!")
        return

    print(f"   🔍 Qwen3 Final Pass: {len(problem_blocks)} blocks still have source language leakage")

    # Unload Typhoon, load Qwen3:1.7b
    unload_model(TYPHOON_MODEL, ollama_url)
    load_model(QWEN3_MODEL, ollama_url, keep_alive="5m")

    try:
        texts_to_fix = [b["text"] for _, _, b, _ in problem_blocks]

        # Use most common source lang among problem blocks
        from collections import Counter
        src_lang_counter = Counter(lang for _, _, _, lang in problem_blocks)
        src = src_lang_counter.most_common(1)[0][0]
        if src in ("unknown", ""):
            src = source_lang

        fixed_texts, failed_indices = translate_blocks_qwen(
            texts_to_fix,
            target_lang,
            src,
            ollama_url,
            model_name=QWEN3_MODEL,
            job_status=job_status,
            job_id=job_id
        )

        # Write results back to doc_result
        for i, (page_key, block_idx, orig_block, _) in enumerate(problem_blocks):
            if i not in failed_indices and fixed_texts[i]:
                doc_result["pages"][page_key]["blocks"][block_idx]["text"] = fixed_texts[i]
                doc_result["pages"][page_key]["blocks"][block_idx]["qwen3_fallback"] = True
                print(f"      ✅ Fixed block {block_idx} on page {page_key}")
            else:
                print(f"      ❌ Block {block_idx} on page {page_key} still failed — keeping Typhoon result")

    finally:
        # Always cleanup: unload Qwen3, preload Typhoon for next job
        unload_model(QWEN3_MODEL, ollama_url)
        preload_model(TYPHOON_MODEL, ollama_url)
        print("   🔄 Qwen3 unloaded, Typhoon preloaded")



def process_translation(job_id: str, file_path: str, source_lang: str, target_lang: str, job_status: dict, translation_mode: str = "typhoon_direct", cache_key: str = None, ocr_engine: str = "typhoon", render_mode: str = "markdown"):
    """
    Background task สำหรับแปลเอกสาร (Single Workflow: OpenCV Layout -> Typhoon OCR -> Render)
    """
    import time
    from app.config import settings
    from app.services.render_service import render_service
    from app.utils.logger import get_job_logger
    from app.services.cache_service import save_to_cache
    
    model = "scb10x/typhoon-translate1.5-4b:latest"
    
    # Set model (auto-unloads previous model to free VRAM)
    translation_service.llm.set_model(model)
    print(f"🔄 Translation Mode: Typhoon Direct")
    print(f"🤖 Using model: {model}")
    
    print(f"🌏 ภาษาต้นฉบับ: {source_lang}")
    print(f"🎯 ภาษาที่จะแปล: {target_lang}")
    print(f"📸 OCR Engine: FORCE TYPHOON (via OpenCV Layout)")
    print(f"🌎 Render Mode: FORCE MARKDOWN/OVERLAY")
    
    # สร้าง logger
    logger = get_job_logger(job_id)
    logger.log_languages(source_lang, target_lang)
    logger.log_ocr_engine("typhoon (opencv layout)")
    logger.log_translation_mode("typhoon_direct")
    
    try:
        # ✅ Check if cancelled before starting OCR
        if job_status.get(job_id, {}).get("cancelled", False):
            print(f"✅ Job {job_id[:8]}... cancelled before OCR started")
            return
        
        # ✅ Check if file still exists (race condition: file deleted after cancel)
        import os
        if not os.path.exists(file_path):
            print(f"⚠️ Job {job_id[:8]}... file deleted (likely cancelled)")
            return
        
        # Step 1: OCR
        # ถ้าเป็น auto ให้ใช้ tha_Thai ไปก่อนเพื่อให้ OCR อ่านไทยได้
        effective_source_lang = "tha_Thai" if source_lang == "auto" else source_lang
        
        job_status[job_id] = {
            "status": "processing",
            "progress": 10,
            "message": "กำลัง OCR...",
            "stats": {  
                "ocr_engine": "typhoon",
                "translation_mode": "typhoon_direct"
            }
        }
        
        logger.log_ocr_start()
        
        # ------------------------------------------------------------------
        # 1. & 2. Run Full OCR Pipeline (OpenCV + Typhoon)
        # ------------------------------------------------------------------
        from app.services.ocr.ocr_pipeline import run_ocr_pipeline
        
        doc_result = run_ocr_pipeline(file_path, source_lang, job_id, job_status)
        
        # Check cancellation after OCR
        if job_status.get(job_id, {}).get("cancelled", False):
            print(f"✅ Job {job_id[:8]}... cancelled successfully (after OCR)")
            return

        # Init global stats
        total_translated = 0
        total_skipped = 0
        total_table_cells = 0
        
        # ---------------------------------------------------------
        # 🤖 Per-Block Language Detection (Hybrid)
        # ---------------------------------------------------------
        # Note: Language detection moved to per-block level in batch_translator
        # Each block will detect using rule-based (fast) or LLM (accurate) as needed
        
        if source_lang == "auto":
            print("🔍 Using per-block language detection...")
            # Will be handled by batch_translator with hybrid approach
        
        # ✅ Check if cancelled after OCR
        if job_status.get(job_id, {}).get("cancelled", False):
            print(f"✅ Job {job_id[:8]}... cancelled successfully (after OCR)")
            return
        
        # ★ Save original preview (ALL pages) for frontend comparison
        try:
             from app.utils.preview_utils import generate_preview_images
             job_output_dir = settings.OUTPUT_DIR / job_id
             generate_preview_images(file_path, job_output_dir, job_id)
        except Exception as e:
            # Non-critical - just log the error
            print(f"⚠️ Could not save original preview: {e}")
            logger.log_info(f"Original preview failed: {e}")
        
        # ✅ Check if cancelled before translation
        if job_status.get(job_id, {}).get("cancelled", False):
            print(f"✅ Job {job_id[:8]}... cancelled successfully (before translation)")
            return
        
        # Step 2: Translate
        job_status[job_id]["progress"] = 50
        job_status[job_id]["message"] = "กำลังแปลภาษา..."
        translate_start = time.time()
        logger.log_translation_start()
        
        total_pages = doc_result["num_pages"]
        
        for page_no in range(1, total_pages + 1):
            # เช็คว่า job ถูกยกเลิกหรือไม่
            if job_status.get(job_id, {}).get("cancelled", False):
                print(f"⚠️ Job {job_id} ถูกยกเลิก - หยุดการแปล")
                job_status[job_id]["status"] = "cancelled"
                job_status[job_id]["message"] = "ยกเลิกกระบวนการแล้ว"
                logger.log_error("Job cancelled by user")
                logger.finalize()
                return
            
            # Support both integer and string page keys (JSON converts int to string)
            page_data = doc_result["pages"].get(page_no) or doc_result["pages"].get(str(page_no))
            
            # Skip if page_data is None (shouldn't happen, but safety check)
            if page_data is None:
                print(f"   ⚠️ Page {page_no} not found in doc_result, skipping...")
                continue
            
            # Translate text blocks - Use Typhoon Direct
            translated_blocks, stats = translation_service.translate_blocks_typhoon(
                page_data["blocks"], 
                target_lang,
                source_lang=source_lang,
                job_status=job_status,
                job_id=job_id
            )

            # Get page key (could be int or string from JSON)
            page_key = page_no if page_no in doc_result["pages"] else str(page_no)
            doc_result["pages"][page_key]["blocks"] = translated_blocks
            total_translated += stats["translated"]
            total_skipped += stats["skipped"]
            
            # Translate tables
            tables = page_data.get("tables", [])
            if tables:
                translated_tables = translation_service.translate_tables(
                    tables, 
                    target_lang
                )
                doc_result["pages"][page_key]["tables"] = translated_tables
                total_table_cells += sum(len(t.get('cells', [])) for t in translated_tables)
            else:
                translated_tables = []
            
            # บันทึก log แต่ละ block
            for idx, block in enumerate(translated_blocks):
                logger.log_block(
                    page_no=page_no,
                    block_idx=idx + 1,
                    original=block.get("original_text", ""),
                    translated=block.get("text", ""),
                    detected_lang=block.get("detected_lang", "unknown"),
                    was_translated=block.get("was_translated", True),
                    qwen3_fallback=block.get("qwen3_fallback", False)
                )
            
            # บันทึก log แต่ละตาราง
            for table_idx, table in enumerate(translated_tables):
                logger.log_table(
                    page_no=page_no,
                    table_idx=table_idx + 1,
                    num_rows=table.get("num_rows", 0),
                    num_cols=table.get("num_cols", 0),
                    cells=table.get("cells", [])
                )
            
            # Update progress (50-80%)
            progress = 50 + int((page_no / total_pages) * 30)
            job_status[job_id]["progress"] = progress
            job_status[job_id]["message"] = f"แปลหน้า {page_no}/{total_pages}..."
        
        translate_duration = time.time() - translate_start
        logger.log_translation_complete(total_translated, total_skipped, translate_duration)

        # Step 2.5: Final Qwen3 Fallback Check (for CJK source OR target languages)
        CJK_LANGS = {"jpn_Jpan", "ja", "zho_Hans", "zho_Hant", "zh", "zh-cn", "kor_Hang", "ko"}
        should_run_final_pass = (
            source_lang in CJK_LANGS or  # JP/ZH/KO as source → check output for remaining src chars
            target_lang in CJK_LANGS or  # JP/ZH/KO as target → check for non-English source leakage
            source_lang == "auto"         # Unknown source → might be CJK
        )
        if should_run_final_pass:
            job_status[job_id]["progress"] = 82
            job_status[job_id]["message"] = "ตรวจสอบคุณภาพการแปล..."
            print("\n🔍 Step 2.5: Running Qwen3 Final Pass for CJK leakage...")
            _run_qwen3_final_pass(
                doc_result,
                source_lang=source_lang,
                target_lang=target_lang,
                job_status=job_status,
                job_id=job_id,
                ollama_url=settings.OLLAMA_URL
            )

            # Re-log blocks that were fixed by Qwen3 (append correction section to each page log)
            from app.config import settings as cfg
            import os
            for page_no in range(1, total_pages + 1):
                page_key = page_no if page_no in doc_result["pages"] else str(page_no)
                page_data = doc_result["pages"].get(page_key)
                if not page_data:
                    continue
                qwen3_fixed = [
                    (idx, block) for idx, block in enumerate(page_data.get("blocks", []))
                    if block.get("qwen3_fallback", False)
                ]
                if qwen3_fixed:
                    log_file = cfg.OUTPUT_DIR / job_id / "logs" / f"page_{page_no:03d}_blocks.txt"
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(f"\n{'='*60}\n")
                        f.write("QWEN3 CORRECTIONS\n")
                        f.write(f"{'='*60}\n")
                        for idx, block in qwen3_fixed:
                            f.write(f"Block {idx + 1} [TRANSLATED] [QWEN3] (detected: {block.get('detected_lang', 'unknown')})\n")
                            f.write(f"  Original: {block.get('original_text', '')}\n")
                            f.write(f"  Result:   {block.get('text', '')}\n")
                            f.write("-" * 60 + "\n")

        # Step 3: Render
        job_status[job_id]["progress"] = 90
        job_status[job_id]["message"] = "กำลังสร้างเอกสาร..."
        
        render_start = time.time()
        output_path = render_service.render_document(job_id, doc_result)
        render_duration = time.time() - render_start
        
        logger.log_render_complete(render_duration, output_path)
        
        # Finalize log
        final_stats = logger.finalize()
        
        # Save to cache if cache_key provided
        if cache_key:
            save_to_cache(cache_key, job_id)
        
        # Done
        job_status[job_id] = {
            "status": "completed",
            "progress": 100,
            "message": "เสร็จสิ้น",
            "output_path": output_path,
            "stats": {
                "ocr_seconds": final_stats["timings"].get("ocr_seconds", 0),
                "translate_seconds": final_stats["timings"].get("translation_seconds", 0),
                "render_seconds": final_stats["timings"].get("render_seconds", 0),
                "total_seconds": final_stats["timings"].get("total_seconds", 0),
                "blocks_translated": total_translated,
                "blocks_skipped": total_skipped,
                "languages": final_stats.get("languages", {}),
                "ocr_engine": "typhoon (opencv)",
                "translation_mode": "typhoon_direct",
                # Use detected language from logger stats, fallback to approximation
                "detected_language": final_stats.get("detected_language", "tha_Thai" if source_lang == "auto" else source_lang)
            }
        }
        
    except Exception as e:
        logger.log_error(str(e))
        import traceback
        traceback.print_exc()
        # ✅ Preserve stats even on error
        existing_stats = job_status.get(job_id, {}).get("stats", {
            "ocr_engine": "typhoon",
            "translation_mode": "typhoon_direct"
        })
        job_status[job_id] = {
            "status": "error",
            "message": f"เกิดข้อผิดพลาด: {str(e)}",
            "stats": existing_stats
        }
