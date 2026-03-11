import time
import os
import re
import fitz
from PIL import Image
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.config import settings
from app.services.ocr import ocr_service
from app.utils.logger import get_job_logger

def run_ocr_pipeline(
    file_path: str, 
    source_lang: str, 
    job_id: str, 
    job_status: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute the full OCR pipeline:
    1. OpenCV Layout Analysis
    2. Crop Generation
    3. Block-by-Block OCR (Typhoon)
    """
    logger = get_job_logger(job_id)
    ocr_start = time.time()
    
    # Update status
    job_status[job_id]["message"] = "กำลังวิเคราะห์ Layout (PaddleOCR)..."
    
    # ------------------------------------------------------------------
    # 1. Layout Analysis (OpenCV)
    # ------------------------------------------------------------------
    print(f"🔷 Running PaddleOCR Layout Analysis...")
    
    # Force 'tha_Thai' if auto to ensure Thai OCR works
    effective_source_lang = "tha_Thai" if source_lang == "auto" else source_lang
    
    # Run OpenCV to get layout
    layout_result = ocr_service.process_document(
        file_path, 
        source_lang=effective_source_lang, 
        ocr_engine="paddle", 
        job_id=job_id,
        job_status=job_status
    )
    
    print(f"✅ PaddleOCR Layout Analysis complete. Blocks found: {sum(len(p['blocks']) for p in layout_result['pages'].values())}")
    
    # [NEW] Merge overlapping blocks to ensure no X/Y coordinate overlap (especially Thai vowels)
    from app.utils.bbox_utils import merge_overlapping_blocks
    total_before = sum(len(p['blocks']) for p in layout_result['pages'].values())
    for page_key, page_data in layout_result["pages"].items():
        page_data["blocks"] = merge_overlapping_blocks(page_data["blocks"])
    total_after = sum(len(p['blocks']) for p in layout_result['pages'].values())
    if total_before != total_after:
        print(f"   🧹 Overlap merging reduced blocks from {total_before} to {total_after}")

    # ------------------------------------------------------------------
    # 2. CROP & OCR PIPELINE (Typhoon Block-by-Block)
    # ------------------------------------------------------------------
    job_status[job_id]["message"] = "กำลัง OCR..."
    job_status[job_id]["progress"] = 30 # Force start at 30%
    
    # Initialize result structure
    doc_result = layout_result
    doc_result["ocr_engine"] = "typhoon (cropped)"
    doc_result["render_mode"] = "markdown" 
    
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
        
        # Save full page image for overlay rendering
        full_page_pix = pdf_page.get_pixmap(dpi=200)
        full_page_path = crop_dir / f"full_page_{page_num_key}.png"
        full_page_pix.save(str(full_page_path))
        
        # ── Debug: Draw detected blocks on page image and save to logs/ ──
        try:
            import cv2
            
            log_dir = settings.OUTPUT_DIR / job_id / "logs"
            os.makedirs(log_dir, exist_ok=True)
            
            # Load the full page image we just saved
            debug_img = cv2.imread(str(full_page_path))
            if debug_img is not None:
                page_w_pts  = page_data.get("width",  pdf_page.rect.width)
                page_h_pts  = page_data.get("height", pdf_page.rect.height)
                img_h_px, img_w_px = debug_img.shape[:2]
                
                # Scale factors: points → pixels (the image is at 200 DPI)
                sx = img_w_px / page_w_pts
                sy = img_h_px / page_h_pts
                
                # Color map per label  (BGR)
                COLORS = {
                    "text":  (50, 200, 50),    # green
                    "table": (0, 220, 220),    # yellow-ish
                    "image": (220, 100, 0),    # blue-ish
                }
                
                for idx, blk in enumerate(blocks):
                    bbox  = blk.get("bbox", {})
                    label = blk.get("label", "text")
                    conf  = blk.get("confidence", 1.0)
                    color = COLORS.get(label, (180, 180, 180))
                    
                    x1 = int(bbox.get("x1", 0) * sx)
                    y1 = int(bbox.get("y1", 0) * sy)
                    x2 = int(bbox.get("x2", 0) * sx)
                    y2 = int(bbox.get("y2", 0) * sy)
                    
                    # Draw filled semi-transparent rectangle
                    overlay = debug_img.copy()
                    cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
                    cv2.addWeighted(overlay, 0.15, debug_img, 0.85, 0, debug_img)
                    
                    # Draw border
                    cv2.rectangle(debug_img, (x1, y1), (x2, y2), color, 2)
                    
                    # Label text
                    tag = f"#{idx+1} {label} {conf:.2f}"
                    font_scale = max(0.4, img_w_px / 2500)
                    (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
                    ty = max(y1 - 4, th + 2)
                    cv2.rectangle(debug_img, (x1, ty - th - 2), (x1 + tw + 4, ty + 2), color, -1)
                    cv2.putText(debug_img, tag, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), 1, cv2.LINE_AA)
                
                debug_path = log_dir / f"page_{int(page_num_key):03d}_blocks_detected.png"
                cv2.imwrite(str(debug_path), debug_img)
                print(f"   🔍 Debug image saved: {debug_path.name}")
        except Exception as _dbg_err:
            print(f"   ⚠️ Debug image generation failed: {_dbg_err}")
        # ─────────────────────────────────────────────────────────────────
        
        if page_num_key not in doc_result["pages"]:
             doc_result["pages"][page_num_key] = {}
        
        doc_result["pages"][page_num_key]["image_path"] = str(full_page_path)
        
        # Prepare args for parallel execution
        block_args = [(i, b, pdf_page, page_num_key, crop_dir, job_id, job_status, source_lang) for i, b in enumerate(blocks)]
        
        # Batch processing
        batch_size = 3
        max_workers = 3
        
        # Custom ThreadPoolExecutor for responsive cancellation
        executor = ThreadPoolExecutor(max_workers=max_workers)
        
        try:
            for i in range(0, len(block_args), batch_size):
                if job_status.get(job_id, {}).get("cancelled", False):
                    print(f"🛑 Batch loop detected cancellation for Job {job_id}")
                    break
                    
                batch = block_args[i : i + batch_size]
                print(f"      🚀 Processing batch {i//batch_size + 1} ({len(batch)} blocks)... [Cancelled: {job_status.get(job_id, {}).get('cancelled', False)}]")
                
                # Submit futures
                future_to_args = {executor.submit(_process_single_block_wrapper, args): args for args in batch}
                
                processed_in_batch = 0
                skipped_in_batch = 0
                
                # Process results as they complete
                for future in as_completed(future_to_args):
                    if job_status.get(job_id, {}).get("cancelled", False):
                        print(f"🛑 Inner loop detected cancellation, breaking batch...")
                        break
                    
                    try:
                        res = future.result()
                        if res: 
                            processed_blocks_count += 1
                            processed_in_batch += 1
                        else: 
                            skipped_blocks_count += 1
                            skipped_in_batch += 1
                    except Exception as e:
                        print(f"      ❌ Validating future result failed: {e}")
                        skipped_blocks_count += 1

                # Update Progress (30-50%)
                current_progress = 30 + int((processed_blocks_count / total_blocks_count) * 20)
                job_status[job_id]["progress"] = current_progress
                
                # Wait for rate limit
                if i + batch_size < len(block_args):
                     if not job_status.get(job_id, {}).get("cancelled", False):
                        time.sleep(2)
        finally:
            # Cleanup executor
            # shutdown(wait=False) allows us to exit immediately even if threads are still running
            # cancel_futures=True prevents pending tasks from starting
            executor.shutdown(wait=False, cancel_futures=True)
        
    pdf_doc.close()
    
    ocr_duration = time.time() - ocr_start
    total_blocks = sum(len(doc_result["pages"][p]["blocks"]) for p in doc_result["pages"])
    logger.log_ocr_complete(doc_result["num_pages"], total_blocks, ocr_duration)
    
    # Update OCR engine for stats
    resolved_ocr = "typhoon (paddle)"
    logger.log_ocr_engine(resolved_ocr)
    
    return doc_result


# Wrapper for concurrent execution
def _process_single_block_wrapper(args):
    return process_single_block(*args)

def process_single_block(i, block, pdf_page, page_num_key, crop_dir, job_id, job_status, source_lang):
    """Refactored unit function for processing one block"""
    
    # Check cancellation early
    if job_status.get(job_id, {}).get("cancelled", False):
        print(f"      🛑 Worker {i} detected cancellation")
        return False
        
    # Use crop_bbox (padded) if available, else standard bbox
    if "crop_bbox" in block:
        bbox = block["crop_bbox"]
    else:
        bbox = block["bbox"]
    
    # Validate bbox dimensions
    if bbox["x2"] <= bbox["x1"] or bbox["y2"] <= bbox["y1"]:
        return False

    rect = fitz.Rect(bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"])
    rect = rect & pdf_page.rect
    
    if rect.width < 1 or rect.height < 1:
        return False
    
    try:
        # Get pixmap (High DPI)
        crop_pix = pdf_page.get_pixmap(dpi=300, clip=rect)
        
        if crop_pix.width < 1 or crop_pix.height < 1:
           return False

        # Save crop
        crop_filename = f"p{page_num_key}_b{i+1}.png"
        crop_path = crop_dir / crop_filename
        crop_pix.save(str(crop_path))
        
        # Check if empty/solid (skip for table — always OCR tables)
        if block.get("label") != "table":
            with Image.open(crop_path) as img_check:
                img_gray = img_check.convert("L")
                pixels = list(img_gray.getdata())
                if not pixels: return False
                    
                avg = sum(pixels) / len(pixels)
                var = sum((x - avg) ** 2 for x in pixels) / len(pixels)
                import math
                std_dev = math.sqrt(var)
                
                # Truly blank / solid-color block — skip entirely
                if std_dev < 5.0:
                    block["text"] = ""
                    return False
                
    except Exception as resize_err:
        print(f"      ⚠️ Error processing block {i}: {resize_err}")
        return False
    
    # ── Handle Image Blocks Directly ───────────────────────────────────────
    is_table   = block.get("label") == "table"
    is_image   = block.get("label") == "image"

    if is_image:
        print(f"      🖼️ Keeping Image Block {i+1} unchanged")
        block["text"]       = ""
        block["image_path"] = str(crop_path)
        block["is_image"]   = True
        return True

    # ── OCR Request with Retry ─────────────────────────────────────────────
    if is_table:
        print(f"      📊 Processing Table Block {i+1}...")
    else:
        print(f"      📝 Processing Text Block {i+1}...")

    for attempt in range(4):  # Initial + 3 Retries
        if job_status.get(job_id, {}).get("cancelled", False):
            return False

        try:
            # Ensure Typhoon loaded
            if ocr_service._typhoon is None:
                from app.services.ocr.typhoon_service import TyphoonOCRService
                ocr_service._typhoon = TyphoonOCRService()

            # Use direct VLM call with strict OCR prompt
            extracted_text = ocr_service._typhoon.process_image_direct(
                str(crop_path),
                source_lang=source_lang,
                is_table=is_table,
            )

            text = extracted_text.strip()
            
            # [NEW] Post-OCR Hallucination Check
            # Prevent pure image blocks (illustrations) from generating repeating OCR garbage
            repeat_match = re.search(r'(.{3,})\1{4,}', text)
            if repeat_match:
                print(f"      🚨 OCR Hallucination detected (loop): '{repeat_match.group(1)}'...")
                if len(text) > 150: # Likely an illustration forced to be read as text
                    print(f"      🖼️ Converting hallucinated region to Image Block")
                    block["text"] = ""
                    block["original_text"] = ""
                    block["image_path"] = str(crop_path)
                    block["is_image"] = True
                    return True
                else:
                    text = text[:repeat_match.start()].strip() # Cut the loop

            block["text"] = text
            block["original_text"] = text

            return True

        except Exception as e:
            if attempt == 3:
                block["text"] = ""
                return True

            wait_time = 5 + (attempt * 3)
            time.sleep(wait_time)

    return False
