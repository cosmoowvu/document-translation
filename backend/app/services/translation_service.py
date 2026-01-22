
# Import from new translation modules
from app.services.translation import translation_service


def process_translation(job_id: str, file_path: str, source_lang: str, target_lang: str, job_status: dict, translation_mode: str = "qwen_direct", cache_key: str = None, ocr_engine: str = "docling"):
    """
    Background task สำหรับแปลเอกสาร
    translation_mode: "qwen_direct", "gemma_direct", "google_qwen", "google_gemma"
    cache_key: ถ้ามี จะ save ลง cache หลังเสร็จ

    source_lang: ภาษาต้นฉบับ สำหรับ RapidOCR
    """
    import time
    from app.config import settings
    from app.services.ocr_service import ocr_service
    from app.services.render_service import render_service
    from app.utils.logger import get_job_logger
    from app.services.cache_service import save_to_cache
    
    # Map translation_mode to model
    mode_to_model = {
        "typhoon_direct": "scb10x/typhoon-translate1.5-4b:latest",  # ✅ Typhoon Translate for Thai↔English
        "qwen_direct": "qwen2.5:3b",  # ✅ Reverted to 3B (GTX 1650 optimized)
        "gemma_direct": "gemma2:2b",
        "nllb_qwen": "qwen2.5:3b",    # ✅ Reverted to 3B (GTX 1650 optimized)
        "nllb_gemma": "gemma2:2b",
        "nllb_llama": "llama3.2:3b"
    }
    
    model = mode_to_model.get(translation_mode, "qwen2.5:3b")
    use_nllb_refine = translation_mode in ["nllb_qwen", "nllb_gemma", "nllb_llama"]
    
    # Set model (auto-unloads previous model to free VRAM)
    translation_service.llm.set_model(model)
    print(f"🔄 Translation Mode: {translation_mode}")
    print(f"🤖 Using model: {model}")
    if use_nllb_refine:
        print(f"🌐 NLLB + LLM Refine enabled")
    
    # แสดงข้อมูลภาษา
    lang_names = {
        "tha_Thai": "ไทย (Thai)",
        "eng_Latn": "อังกฤษ (English)",
        "zho_Hans": "จีนตัวย่อ (Chinese Simplified)",
        "zho_Hant": "จีนตัวเต็ม (Chinese Traditional)",
        "jpn_Jpan": "ญี่ปุ่น (Japanese)"
    }
    src_display = lang_names.get(source_lang, source_lang)
    tgt_display = lang_names.get(target_lang, target_lang)
    print(f"🌏 ภาษาต้นฉบับ: {src_display}")
    print(f"🎯 ภาษาที่จะแปล: {tgt_display}")
    print(f"📸 OCR Engine: {ocr_engine.upper()}")
    
    # สร้าง logger
    logger = get_job_logger(job_id)
    logger.log_languages(source_lang, target_lang)
    logger.log_ocr_engine(ocr_engine)  # ✅ Log OCR engine
    logger.log_translation_mode(translation_mode)  # ✅ Log translation mode
    
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
        job_status[job_id] = {
            "status": "processing",
            "progress": 10,
            "message": "กำลังดึงข้อความ / OCR...",
            "stats": {  # ✅ Add stats from start
                "ocr_engine": ocr_engine,
                "translation_mode": translation_mode
            }
        }
        
        logger.log_ocr_start()
        ocr_start = time.time()
        
        # ✅ Pass OCR engine selection
        doc_result = ocr_service.process_document(file_path, source_lang=source_lang, ocr_engine=ocr_engine)
        
        ocr_duration = time.time() - ocr_start
        total_blocks = sum(len(doc_result["pages"][p]["blocks"]) for p in doc_result["pages"])
        logger.log_ocr_complete(doc_result["num_pages"], total_blocks, ocr_duration)
        
        # ✅ Check if cancelled after OCR
        if job_status.get(job_id, {}).get("cancelled", False):
            print(f"✅ Job {job_id[:8]}... cancelled successfully (after OCR)")
            return
        
        # ★ Save original preview (ALL pages) for frontend comparison
        try:
            job_output_dir = settings.OUTPUT_DIR / job_id
            job_output_dir.mkdir(parents=True, exist_ok=True)
            
            # Convert all pages of original for preview
            from PIL import Image
            import fitz  # PyMuPDF
            
            # Open PDF and convert all pages
            pdf_doc = fitz.open(file_path)
            for page_num in range(len(pdf_doc)):
                page = pdf_doc[page_num]
                pix = page.get_pixmap(dpi=150)
                
                # Save as PNG with same naming convention as translated
                preview_path = job_output_dir / f"original_{page_num + 1:03d}.png"
                pix.save(str(preview_path))
            
            logger.log_info(f"Saved {len(pdf_doc)} original preview pages")
            pdf_doc.close()
        except Exception as e:
            # Non-critical - just log the error
            print(f"⚠️ Could not save original preview: {e}")
            logger.log_info(f"Original preview failed: {e}")
        
        # ✅ Check if cancelled before translation
        if job_status.get(job_id, {}).get("cancelled", False):
            print(f"✅ Job {job_id[:8]}... cancelled successfully (before translation)")
            return
        
        # Step 2: Translate
        job_status[job_id]["progress"] = 30
        job_status[job_id]["message"] = "กำลังแปลภาษา..."
        
        logger.log_translation_start()
        translate_start = time.time()
        
        total_pages = doc_result["num_pages"]
        total_translated = 0
        total_skipped = 0
        total_table_cells = 0
        
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
            
            # Translate text blocks - choose method based on mode
            if use_nllb_refine:
                # NLLB + LLM Refine (now sync)
                translated_blocks, stats = translation_service.translate_blocks_nllb_refine(
                    page_data["blocks"],
                    target_lang,
                    refine_model=model,
                    source_lang=source_lang,  # ✅ ส่ง source_lang จาก job ตรงๆ ไม่ใช้ auto-detect
                    job_status=job_status,
                    job_id=job_id,
                    page_no=page_no,
                    total_pages=total_pages
                )
            elif translation_mode == "typhoon_direct":
                # Typhoon Direct - use specialized translation method
                # ✅ Pass job_status and job_id for cancel support
                translated_blocks, stats = translation_service.translate_blocks_typhoon(
                    page_data["blocks"], 
                    target_lang,
                    source_lang=source_lang,
                    job_status=job_status,
                    job_id=job_id
                )
            else:
                # Direct LLM translation (Qwen/Gemma)
                # ✅ Pass job_status and job_id for cancel  support
                translated_blocks, stats = translation_service.translate_blocks(
                    page_data["blocks"], 
                    target_lang,
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
                    use_nllb_refine=use_nllb_refine,
                    refine_model=model
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
                    nllb_translated=block.get("nllb_translated")  # Pass NLLB translation if exists
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
            
            # Update progress
            progress = 30 + int((page_no / total_pages) * 50)
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
                "ocr_engine": doc_result.get("ocr_engine", ocr_engine),  # ✅ Add OCR engine
                "translation_mode": translation_mode  # ✅ Add translation mode
            }
        }
        
    except Exception as e:
        logger.log_error(str(e))
        import traceback
        traceback.print_exc()
        # ✅ Preserve stats even on error
        existing_stats = job_status.get(job_id, {}).get("stats", {
            "ocr_engine": ocr_engine,
            "translation_mode": translation_mode
        })
        job_status[job_id] = {
            "status": "error",
            "message": f"เกิดข้อผิดพลาด: {str(e)}",
            "stats": existing_stats
        }
