import fitz  # PyMuPDF
from pathlib import Path
from app.utils.logger import get_job_logger

def generate_preview_images(file_path: str, output_dir: Path, job_id: str) -> bool:
    """
    Generate preview images for all pages of a document.
    Saves as PNGs in output_dir/original_XXX.png
    """
    logger = get_job_logger(job_id)
    
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Open PDF and convert all pages
        pdf_doc = fitz.open(file_path)
        for page_num in range(len(pdf_doc)):
            page = pdf_doc[page_num]
            pix = page.get_pixmap(dpi=150)
            
            # Save as PNG with same naming convention as translated
            preview_path = output_dir / f"original_{page_num + 1:03d}.png"
            pix.save(str(preview_path))
        
        logger.log_info(f"Saved {len(pdf_doc)} original preview pages")
        pdf_doc.close()
        return True
        
    except Exception as e:
        # Non-critical - just log the error
        print(f"⚠️ Could not save original preview: {e}")
        logger.log_info(f"Original preview failed: {e}")
        return False
