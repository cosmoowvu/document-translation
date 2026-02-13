
# Import from new translation modules
from app.services.translation import translation_service



def process_translation(job_id: str, file_path: str, source_lang: str, target_lang: str, job_status: dict, translation_mode: str = "typhoon_direct", cache_key: str = None, ocr_engine: str = "docling", render_mode: str = "canvas"):
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
    
    print(f"🌎 Render Mode: {render_mode.upper()}")
    
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
        
        # ✅ Pass OCR engine selection and job_id
        # ✅ Pass OCR engine selection and job_id
        
        # [NEW] If Render Mode is Markdown, use OpenCV for Layout Analysis first
        if render_mode == "markdown":
            print(f"📷 Markdown Mode detected: Running OpenCV Layout Analysis...")
            job_status[job_id]["message"] = "กำลังวิเคราะห์ Layout (OpenCV)..."
            
            # Run OpenCV to get layout (and save debug images)
            layout_result = ocr_service.process_document(
                file_path, 
                source_lang=effective_source_lang, 
                ocr_engine="opencv", # Force OpenCV for layout
                job_id=job_id
            )
            print(f"✅ OpenCV Layout Analysis complete. Blocks found: {sum(len(p['blocks']) for p in layout_result['pages'].values())}")
            
            # ------------------------------------------------------------------
            # ✂️ CROP & OCR PIPELINE (Typhoon Block-by-Block)
            # ------------------------------------------------------------------
            import fitz
            import os
            from PIL import Image
            
            # Update status
            job_status[job_id]["message"] = "กำลังทยอย OCR ทีละส่วน..."
            
            # Initialize result structure (mimic doc_result)
            doc_result = layout_result # Use OpenCV layout as base
            doc_result["ocr_engine"] = "typhoon (cropped)"
            doc_result["render_mode"] = render_mode # Pass render mode to renderer
            
            # Temporary directory for crops
            crop_dir = settings.OUTPUT_DIR / job_id / "crops"
            os.makedirs(crop_dir, exist_ok=True)
            
            # Open PDF for cropping
            pdf_doc = fitz.open(file_path)
            
            total_blocks_count = sum(len(p['blocks']) for p in layout_result['pages'].values())
            processed_blocks_count = 0
            skipped_blocks_count = 0
            
            # Iterate pages
            for page_num_key, page_data in layout_result["pages"].items():
                page_idx = int(page_num_key) - 1
                if page_idx >= len(pdf_doc): continue
                
                pdf_page = pdf_doc[page_idx]
                blocks = page_data["blocks"]
                
                # Check cancellation
                if job_status.get(job_id, {}).get("cancelled", False):
                     break

                print(f"   📄 Page {page_num_key}: Processing {len(blocks)} blocks...")
                
                # Define helper function for parallel processing
                # Save full page image for overlay rendering
                # Use high DPI (200) for good quality overlay
                full_page_pix = pdf_page.get_pixmap(dpi=200)
                full_page_path = crop_dir / f"full_page_{page_num_key}.png"
                full_page_pix.save(str(full_page_path))
                
                if page_num_key not in doc_result["pages"]:
                     doc_result["pages"][page_num_key] = {}
                
                doc_result["pages"][page_num_key]["image_path"] = str(full_page_path)
                print(f"   🖼️ Saved full page image for Page {page_num_key}: {full_page_path}")
                
                def process_single_block(args):
                    i, block, pdf_page, page_num_key = args
                    
                    # Check cancellation early
                    if job_status.get(job_id, {}).get("cancelled", False):
                        return False
                        
                    # Use crop_bbox (padded) if available, else standard bbox
                    # Use crop_bbox (padded) if available, else standard bbox
                    if "crop_bbox" in block:
                        bbox = block["crop_bbox"]
                    else:
                        bbox = block["bbox"]
                    
                    # Validate bbox dimensions
                    if bbox["x2"] <= bbox["x1"] or bbox["y2"] <= bbox["y1"]:
                        print(f"      ⚠️ Skipping invalid bbox: {bbox}")
                        return False

                    rect = fitz.Rect(bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"])
                    
                    # Intersect with page valid area
                    rect = rect & pdf_page.rect
                    
                    if rect.width < 1 or rect.height < 1:
                        print(f"      ⚠️ Skipping empty crop after intersection: {rect}")
                        return False
                    
                    try:
                        # Get pixmap (High DPI)
                        crop_pix = pdf_page.get_pixmap(dpi=300, clip=rect)
                        
                        if crop_pix.width < 1 or crop_pix.height < 1:
                           print(f"      ⚠️ Generated empty pixmap for {rect}")
                           return False

                        # Save crop
                        crop_filename = f"p{page_num_key}_b{i+1}.png"
                        crop_path = crop_dir / crop_filename
                        crop_pix.save(str(crop_path))
                        
                        # Check if empty/solid
                        with Image.open(crop_path) as img_check:
                            img_gray = img_check.convert("L")
                            pixels = list(img_gray.getdata())
                            if not pixels:
                                return False
                                
                            avg = sum(pixels) / len(pixels)
                            var = sum((x - avg) ** 2 for x in pixels) / len(pixels)
                            import math
                            std_dev = math.sqrt(var)
                            
                            if std_dev < 10.0:
                                print(f"      ⚠️ Skipping low-detail crop (StdDev: {std_dev:.2f})")
                                block["text"] = "" 
                                return False
                                
                    except Exception as resize_err:
                        print(f"      ⚠️ Error processing block {i}: {resize_err}")
                        return False
                    
                    # OCR Request
                    try:
                        if ocr_service._typhoon is None:
                            from app.services.ocr.typhoon_service import TyphoonOCRService
                            ocr_service._typhoon = TyphoonOCRService()
                            
                        crop_result = ocr_service._typhoon.process_document(str(crop_path), source_lang)
                        
                        extracted_text = ""
                        # Fix: TyphoonOCRService returns blocks inside pages[1]["blocks"]
                        # Handle both integer and string keys for page number
                        page_data = None
                        if "pages" in crop_result:
                            if 1 in crop_result["pages"]:
                                page_data = crop_result["pages"][1]
                            elif "1" in crop_result["pages"]:
                                page_data = crop_result["pages"]["1"]
                        
                        if page_data and "blocks" in page_data and page_data["blocks"]:
                             extracted_text = page_data["blocks"][0].get("text", "")
                        
                        # Fallback: if text is in root or other format (just in case)
                        if not extracted_text and "text" in crop_result:
                            extracted_text = crop_result["text"]

                        block["text"] = extracted_text.strip()
                        block["original_text"] = extracted_text.strip()
                        return True
                        
                    except Exception as e:
                        print(f"      ❌ Failed to OCR crop {crop_filename}: {e}")
                        block["text"] = ""
                        return True # Count as processed (failed but tried)

                # Prepare args for parallel execution
                block_args = [(i, b, pdf_page, page_num_key) for i, b in enumerate(blocks)]
                
                # Execute in batches to avoid Rate Limit (Manual Batching)
                batch_size = 5
                import time
                
                from concurrent.futures import ThreadPoolExecutor
                max_workers = 5 # Workers per batch
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    for i in range(0, len(block_args), batch_size):
                        # Get current batch
                        batch = block_args[i : i + batch_size]
                        print(f"      🚀 Processing batch {i//batch_size + 1} ({len(batch)} blocks)...")
                        
                        # Process batch in parallel
                        results = list(executor.map(process_single_block, batch))
                        
                        # Update stats immediately
                        for res in results:
                            if res:
                                processed_blocks_count += 1
                            else:
                                skipped_blocks_count += 1
                        
                        # Update Progress
                        current_progress = 10 + int((processed_blocks_count / total_blocks_count) * 20)
                        job_status[job_id]["progress"] = current_progress
                        
                        # Wait before next batch (Rate Limit Prevention)
                        if i + batch_size < len(block_args):
                            print(f"      ⏳ Waiting 2s before next batch...")
                            time.sleep(2)
            
            print(f"✅ Crop & OCR complete. Total Processed: {processed_blocks_count}, Skipped: {skipped_blocks_count}")
                    
            pdf_doc.close()
            print(f"✅ Crop & OCR complete.")
        else:
            # Normal Canvas Mode
            doc_result = ocr_service.process_document(
                file_path, 
                source_lang=effective_source_lang, 
                ocr_engine=ocr_engine,
                job_id=job_id
            )
        
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
