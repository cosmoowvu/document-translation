
# Import from new translation modules
from app.services.translation import translation_service



def process_translation(job_id: str, file_path: str, source_lang: str, target_lang: str, job_status: dict, translation_mode: str = "typhoon_direct", cache_key: str = None, ocr_engine: str = "typhoon", render_mode: str = "markdown"):
    """
    Background task สำหรับแปลเอกสาร (Single Workflow: OpenCV Layout -> Typhoon OCR -> Render)
    """
    import time
    from app.config import settings
    from app.services.render_service import render_service
    from app.utils.logger import get_job_logger
    from app.services.cache_service import save_to_cache
    
    # Map translation_mode to model
    # We only support Typhoon now
    mode_to_model = {
        "typhoon_direct": "scb10x/typhoon-translate1.5-4b:latest",
    }
    
    model = mode_to_model.get("typhoon_direct") # Force Typhoon
    
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
        
        skip_translation_phase = False

        
        # ✅ Check if cancelled after OCR
        if job_status.get(job_id, {}).get("cancelled", False):
            print(f"✅ Job {job_id[:8]}... cancelled successfully (after OCR)")
            return
        
        # ★ Save original preview (ALL pages) for frontend comparison
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
        if skip_translation_phase:
             translate_start = time.time()
             pass
        else:
            job_status[job_id]["progress"] = 50
            job_status[job_id]["message"] = "กำลังแปลภาษา..."
            translate_start = time.time()
        
        logger.log_translation_start()
        
        total_pages = doc_result["num_pages"]
        
        # Loop pages (Run only if NOT skipping)
        if not skip_translation_phase:
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
                        target_lang,
                        use_nllb_refine=False, # Disable NLLB
                        refine_model=None
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
                        was_translated=block.get("was_translated", True)
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
                job_status[job_id]["message"] = f"แปลหน้า {page_no}/{total_pages}... (แปล {stats['translated']}, ข้าม {stats['skipped']})"
            
        translate_duration = time.time() - translate_start
        logger.log_translation_complete(total_translated, total_skipped, translate_duration)
        
        # Step 3: Render
        job_status[job_id]["progress"] = 80
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
                "translation_mode": "typhoon_direct",
                "detected_language": source_lang if source_lang != "auto" else "tha_Thai" # Approximated
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
