from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import uvicorn
import shutil
import os
import tempfile
from typing import List, Dict, Any

# Disable oneDNN to fix Windows compatibility issues
os.environ['FLAGS_use_mkldnn'] = '0'
os.environ['MKLDNN_ENABLED'] = '0'
os.environ['DNNL_VERBOSE'] = '0'

from paddleocr import PaddleOCR

app = FastAPI(title="PaddleOCR Service")

# Cache OCR engines
ocr_engines = {}

def get_ocr_engine(lang: str = 'en'):
    if lang not in ocr_engines:
        print(f"📥 Loading PaddleOCR ({lang}) [CPU mode]...")
        # PaddleOCR 2.7.x - CPU mode (GPU requires cuDNN installation)
        ocr_engines[lang] = PaddleOCR(
            use_angle_cls=True,
            lang=lang,
            use_gpu=False,
            show_log=False
        )
        print(f"✅ PaddleOCR ({lang}) [CPU mode] ready")
    return ocr_engines[lang]

def extract_blocks_from_result(result: List, page_height: float) -> List[Dict]:
    """Convert PaddleOCR result to standard block format"""
    blocks = []
    
    if not result or not result[0]:
        return blocks
    
    for line in result[0]:
        bbox_points = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
        text_info = line[1]     # (text, confidence)
        
        text = text_info[0]
        confidence = text_info[1]
        
        # Skip low confidence results
        if confidence < 0.5:
            continue
        
        # Convert polygon to rectangle (top-left and bottom-right)
        x_coords = [point[0] for point in bbox_points]
        y_coords = [point[1] for point in bbox_points]
        
        x1 = min(x_coords)
        y1 = min(y_coords)
        x2 = max(x_coords)
        y2 = max(y_coords)
        
        blocks.append({
            "text": text,
            "bbox": {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2
            },
            "label": "text",
            "confidence": confidence
        })
    
    return blocks

@app.post("/process")
async def process_document(
    file: UploadFile = File(...),
    lang: str = Form("en")
):
    try:
        # Save uploaded file temporarily
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
            
        try:
            ocr = get_ocr_engine(lang)
            
            # Process with PaddleOCR (cls=True for text direction detection)
            result = ocr.ocr(tmp_path, cls=True)
            
            # Response structure
            response_data = {
                "num_pages": 1,
                "pages": {},
                "ocr_engine": "paddleocr"
            }
            
            # Determine if it's PDF or Image
            is_pdf = tmp_path.lower().endswith('.pdf')
            
            if is_pdf:
                import fitz # PyMuPDF
                doc = fitz.open(tmp_path)
                response_data["num_pages"] = len(doc)
                
                for i, page_result in enumerate(result):
                    page = doc[i]
                    page_height = page.rect.height
                    page_width = page.rect.width
                    
                    blocks = extract_blocks_from_result([page_result] if page_result else [], page_height)
                    
                    response_data["pages"][i + 1] = {
                        "width": page_width,
                        "height": page_height,
                        "blocks": blocks,
                        "tables": []
                    }
                doc.close()
                
            else:
                # Image
                # We need image dimensions
                from PIL import Image
                img = Image.open(tmp_path)
                width, height = img.size
                img.close()  # Close file before cleanup
                
                blocks = extract_blocks_from_result(result, height)
                
                response_data["pages"][1] = {
                    "width": width,
                    "height": height,
                    "blocks": blocks,
                    "tables": []
                }
                
            return response_data
            
        finally:
            # Cleanup temp file (ignore errors if file is still locked)
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass  # File may still be locked, will be cleaned up later
                
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    print("🚀 Starting PaddleOCR Service on port 8001...")
    uvicorn.run("paddle_service:app", host="0.0.0.0", port=8001, reload=True)
