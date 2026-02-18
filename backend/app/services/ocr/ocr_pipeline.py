import time
import os
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
    job_status[job_id]["message"] = "กำลังวิเคราะห์ Layout (OpenCV)..."
    
    # ------------------------------------------------------------------
    # 1. Layout Analysis (OpenCV)
    # ------------------------------------------------------------------
    print(f"📷 Running OpenCV Layout Analysis...")
    
    # Force 'tha_Thai' if auto to ensure Thai OCR works
    effective_source_lang = "tha_Thai" if source_lang == "auto" else source_lang
    
    # Run OpenCV to get layout
    layout_result = ocr_service.process_document(
        file_path, 
        source_lang=effective_source_lang, 
        ocr_engine="opencv", 
        job_id=job_id,
        job_status=job_status
    )
    
    print(f"✅ OpenCV Layout Analysis complete. Blocks found: {sum(len(p['blocks']) for p in layout_result['pages'].values())}")
    
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
    resolved_ocr = "typhoon (opencv)"
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
        
        # Check if empty/solid
        with Image.open(crop_path) as img_check:
            img_gray = img_check.convert("L")
            pixels = list(img_gray.getdata())
            if not pixels: return False
                
            avg = sum(pixels) / len(pixels)
            var = sum((x - avg) ** 2 for x in pixels) / len(pixels)
            import math
            std_dev = math.sqrt(var)
            
            if std_dev < 10.0 and block.get("label") != "table":
                block["text"] = "" 
                return False
                
    except Exception as resize_err:
        print(f"      ⚠️ Error processing block {i}: {resize_err}")
        return False
    
    # OCR Request with Retry
    is_table = block.get("label") == "table"
    if is_table:
        print(f"      📊 Processing Table Block {i+1}...")

    for attempt in range(4): # Initial + 3 Retries
        if job_status.get(job_id, {}).get("cancelled", False):
            return False

        try:
            # Ensure Typhoon loaded
            if ocr_service._typhoon is None:
                from app.services.ocr.typhoon_service import TyphoonOCRService
                ocr_service._typhoon = TyphoonOCRService()
                
            # Use direct VLM call with strict OCR prompt (prevents hallucination)
            extracted_text = ocr_service._typhoon.process_image_direct(
                str(crop_path),
                source_lang=source_lang,
                is_table=is_table
            )

            block["text"] = extracted_text.strip()
            block["original_text"] = extracted_text.strip()
            return True
            
        except Exception as e:
            if attempt == 3:
                block["text"] = ""
                return True 
            
            wait_time = 5 + (attempt * 3)
            time.sleep(wait_time)
            
    return False
