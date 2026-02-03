
# Import from new translation modules
from app.services.translation import translation_service



def process_translation(job_id: str, file_path: str, source_lang: str, target_lang: str, job_status: dict, translation_mode: str = "typhoon_direct", cache_key: str = None, ocr_engine: str = "docling"):
    """
    Background task สำหรับแปลเอกสาร (Typhoon Only)
    """
    import time
    from app.config import settings
    from app.services.ocr import ocr_service
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
    print(f"📸 OCR Engine: {ocr_engine.upper()}")
    
    # สร้าง logger
    logger = get_job_logger(job_id)
    logger.log_languages(source_lang, target_lang)
    logger.log_ocr_engine(ocr_engine)
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
            "message": "กำลังดึงข้อความ / OCR...",
            "stats": {  
                "ocr_engine": ocr_engine,
                "translation_mode": "typhoon_direct"
            }
        }
        
        logger.log_ocr_start()
        ocr_start = time.time()
        
        # ✅ Pass OCR engine selection
        doc_result = ocr_service.process_document(file_path, source_lang=effective_source_lang, ocr_engine=ocr_engine)
        
        ocr_duration = time.time() - ocr_start
        total_blocks = sum(len(doc_result["pages"][p]["blocks"]) for p in doc_result["pages"])
        logger.log_ocr_complete(doc_result["num_pages"], total_blocks, ocr_duration)
        
        # ✅ Update OCR engine to resolved one (e.g. "docling (auto)") to fix cache
        resolved_ocr = doc_result.get("ocr_engine", ocr_engine)
        logger.log_ocr_engine(resolved_ocr)

        # Init global stats
        total_translated = 0
        total_skipped = 0
        total_table_cells = 0
        
        # ---------------------------------------------------------
        # 🤖 Auto-Detect Language Logic
        # ---------------------------------------------------------
        if source_lang == "auto":
            print("🔍 Auto-detecting language from OCR results...")
            
            # 1. Sample text from first 3 pages
            sample_text = ""
            pages_to_check = list(doc_result["pages"].keys())[:3]
            for page_key in pages_to_check:
                blocks = doc_result["pages"][page_key]["blocks"]
                for block in blocks[:10]: # Check first 10 blocks per page
                    sample_text += block.get("text", "") + " "

            # 2. Use LLM for robust detection
            detected_lang = translation_service.llm.detect_language(sample_text)
            
            # Print simplified log for clarity
            total_chars = len(sample_text.strip())
            print(f"   🤖 Detected Language (LLM): {detected_lang} (from {total_chars} samples)")
            
            # Save to logger for caching
            logger.log_detected_language(detected_lang)
            
            # 3. Update source_lang
            source_lang = detected_lang
            
            # 4. Check if we need to skip translation
            if source_lang == target_lang:
                print(f"   ⏭️ Source matches Target ({source_lang}). Skipping translation.")
                
                # -- SKIP LOGIC --
                # Just copy original text to "text" field
                for page_key in doc_result["pages"]:
                    page = doc_result["pages"][page_key]
                    for block in page["blocks"]:
                        block["original_text"] = block.get("text", "") # Ensure original is set
                        block["text"] = block.get("text", "") # Result = Original
                        block["detected_lang"] = source_lang
                        block["was_translated"] = False
                    
                # Calculate stats
                total_translated = 0
                total_skipped = total_blocks

                # Proceed to Render Step directly
                job_status[job_id]["progress"] = 80
                job_status[job_id]["message"] = f"ภาษาตรงกัน ({source_lang}) - ข้ามการแปล..."
                
                # We need to skip the huge loop below.
                # Let's set a flag
                skip_translation_phase = True
            else:
                 print(f"   ▶️ Proceeding to translate {source_lang} -> {target_lang}")
                 skip_translation_phase = False
        else:
             skip_translation_phase = False

        
        # ✅ Check if cancelled after OCR
        if job_status.get(job_id, {}).get("cancelled", False):
            print(f"✅ Job {job_id[:8]}... cancelled successfully (after OCR)")
            return
        
        # ★ Save original preview (ALL pages) for frontend comparison
        try:
            job_output_dir = settings.OUTPUT_DIR / job_id
            job_output_dir.mkdir(parents=True, exist_ok=True)
            
            # Convert all pages of original for preview
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
        if skip_translation_phase:
             translate_start = time.time()
             pass
        else:
            job_status[job_id]["progress"] = 30
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
                "ocr_engine": doc_result.get("ocr_engine", ocr_engine),
                "translation_mode": "typhoon_direct",
                "detected_language": detected_lang if 'detected_lang' in locals() and source_lang == detected_lang else None
            }
        }
        
    except Exception as e:
        logger.log_error(str(e))
        import traceback
        traceback.print_exc()
        # ✅ Preserve stats even on error
        existing_stats = job_status.get(job_id, {}).get("stats", {
            "ocr_engine": ocr_engine,
            "translation_mode": "typhoon_direct"
        })
        job_status[job_id] = {
            "status": "error",
            "message": f"เกิดข้อผิดพลาด: {str(e)}",
            "stats": existing_stats
        }
