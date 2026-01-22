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

def extract_blocks_from_result(result: List, page_height: float, pixel_to_point_ratio: float = 1.0) -> List[Dict]:
    """
    Convert PaddleOCR result to standard block format
    
    Args:
        result: PaddleOCR detection result
        page_height: Height in pixels (unused for now, kept for compatibility)
        pixel_to_point_ratio: Ratio to convert pixels to points (points_per_pixel)
    """
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
        
        # Get pixel coordinates
        x1_px = min(x_coords)
        y1_px = min(y_coords)
        x2_px = max(x_coords)
        y2_px = max(y_coords)
        
        # ✅ Convert pixels to points
        x1 = x1_px * pixel_to_point_ratio
        y1 = y1_px * pixel_to_point_ratio
        x2 = x2_px * pixel_to_point_ratio
        y2 = y2_px * pixel_to_point_ratio
        
        # Debug: Print first block conversion
        if len(blocks) == 0:
            print(f"   🔍 Coordinate conversion - ratio={pixel_to_point_ratio:.4f}")
            print(f"      Pixel: ({x1_px:.1f}, {y1_px:.1f}) -> ({x2_px:.1f}, {y2_px:.1f})")
            print(f"      Point: ({x1:.1f}, {y1:.1f}) -> ({x2:.1f}, {y2:.1f})")
        
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
                from PIL import Image as PILImage
                import io
                
                doc = fitz.open(tmp_path)
                num_pages = len(doc)
                response_data["num_pages"] = num_pages
                
                # ✅ Loop through ALL pages in PDF, not just pages with OCR results
                for i in range(num_pages):
                    page = doc[i]
                    
                    # Get OCR result for this page (may be None if no text detected)
                    page_result = result[i] if i < len(result) and result[i] is not None else None
                    
                    # ✅ PDF pages dimensions in points (PyMuPDF uses points)
                    page_width_pts = page.rect.width
                    page_height_pts = page.rect.height
                    
                    # ✅ PaddleOCR converts PDF internally - we need to detect what DPI it used
                    # Get the actual image dimensions from the first detected text box
                    pixel_width = None
                    pixel_height = None
                    
                    if page_result and len(page_result) > 0:
                        # Find max coordinates to determine image size
                        max_x = 0
                        max_y = 0
                        for line in page_result:
                            bbox_points = line[0]
                            for point in bbox_points:
                                max_x = max(max_x, point[0])
                                max_y = max(max_y, point[1])
                        
                        pixel_width = max_x
                        pixel_height = max_y
                        
                        print(f"   📐 Page {i+1}: Detected max coordinates: {pixel_width:.0f}x{pixel_height:.0f} px")
                    
                    # Fallback: render at 200 DPI if no text detected
                    if pixel_width is None or pixel_width == 0:
                        # Assume PaddleOCR default DPI (usually 200-300)
                        assumed_dpi = 200
                        pixel_width = page_width_pts * assumed_dpi / 72
                        pixel_height = page_height_pts * assumed_dpi / 72
                        print(f"   ⚠️ Page {i+1}: No text detected, assuming {assumed_dpi} DPI")
                    
                    # ✅ Calculate conversion ratio: points per pixel
                    pixel_to_point_ratio = page_width_pts / pixel_width
                    
                    print(f"   📄 Page {i+1}: {pixel_width:.0f}x{pixel_height:.0f} px -> {page_width_pts:.1f}x{page_height_pts:.1f} pts (ratio={pixel_to_point_ratio:.4f})")
                    
                    blocks = extract_blocks_from_result(
                        [page_result] if page_result else [], 
                        pixel_height,
                        pixel_to_point_ratio
                    )
                    
                    response_data["pages"][i + 1] = {
                        "width": page_width_pts,   # ✅ Points
                        "height": page_height_pts, # ✅ Points
                        "blocks": blocks,          # ✅ bbox in points
                        "tables": []
                    }
                doc.close()
                
            else:
                # Image
                from PIL import Image
                img = Image.open(tmp_path)
                pixel_width, pixel_height = img.size
                
                # ✅ Try to get DPI from image metadata, default to 300 DPI (common scan quality)
                dpi = img.info.get('dpi', (300, 300))[0] if isinstance(img.info.get('dpi'), tuple) else 300
                img.close()  # Close file before cleanup
                
                # ✅ Convert pixels to points (72 points = 1 inch)
                # Formula: points = pixels * 72 / DPI
                pixel_to_point_ratio = 72.0 / dpi
                width_pts = pixel_width * pixel_to_point_ratio
                height_pts = pixel_height * pixel_to_point_ratio
                
                print(f"   🖼️ Image: {pixel_width}x{pixel_height} px @ {dpi} DPI -> {width_pts:.1f}x{height_pts:.1f} pts (ratio={pixel_to_point_ratio:.4f})")
                
                blocks = extract_blocks_from_result(result, pixel_height, pixel_to_point_ratio)
                
                response_data["pages"][1] = {
                    "width": width_pts,    # ✅ Points
                    "height": height_pts,  # ✅ Points  
                    "blocks": blocks,      # ✅ bbox in points
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
