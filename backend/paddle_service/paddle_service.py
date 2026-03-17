"""
paddle_service.py
FastAPI microservice wrapping PaddleOCR engines.

Endpoints:
  POST /process   – Legacy: full OCR (text extraction) via PaddleOCR
  POST /detect    – NEW: Layout Analysis only.
                    Runs PicoDet (layout) + DBNet (text line detection),
                    returns block metadata (label, bbox) for each page.
                    The caller (ocr_pipeline.py) handles cropping & Typhoon OCR.
"""

# IMPORTANT: langchain_shim must be the very first import so that
# sys.modules is patched before paddleocr/paddlex attempt to load.
import langchain_shim  # noqa: F401

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import uvicorn
import shutil
import os
import tempfile
import fitz
from typing import List, Dict, Any

# Disable oneDNN to fix Windows compatibility issues
os.environ['FLAGS_use_mkldnn'] = '0'
os.environ['MKLDNN_ENABLED'] = '0'
os.environ['DNNL_VERBOSE'] = '0'

import numpy as np
import cv2
from paddleocr import PaddleOCR

app = FastAPI(title="PaddleOCR Service")

# ---------------------------------------------------------------------------
# Engine caches
# ---------------------------------------------------------------------------
_struct_engine = None   # PicoDet Layout Detection
_det_engine    = None   # DBNet Text Detection


def get_layout_engines():
    """Lazy-load PicoDet layout and DBNet text detection engines."""
    global _struct_engine, _det_engine
    if _struct_engine is None or _det_engine is None:
        print("📥 Loading PaddleX Layout & Text-Detection engines...")
        from paddlex import create_model
        # PP-DocLayout-S: document-optimized layout detection (table/figure/text)
        _struct_engine = create_model("PP-DocLayout-S")
        # PP-OCRv5_mobile_det: latest DBNet text line detection
        _det_engine    = create_model("PP-OCRv5_mobile_det")
        print("✅ PaddleX engines ready")
    return _struct_engine, _det_engine


# ---------------------------------------------------------------------------
# /detect endpoint  (NEW)
# ---------------------------------------------------------------------------

@app.post("/detect")
async def detect_layout(
    file: UploadFile = File(...),
):
    """
    Layout Detection via PicoDet + DBNet.

    Returns JSON:
    {
      "num_pages": N,
      "pages": {
        "1": {
          "width_px": W,
          "height_px": H,
          "blocks": [
            {
              "label": "text" | "table" | "image",
              "bbox": [x1, y1, x2, y2],      # pixel coords (no padding)
              "crop_bbox": [x1, y1, x2, y2], # pixel coords (padded for OCR)
              "confidence": float
            }, ...
          ]
        }
      }
    }
    """
    from detection import (
        get_paddle_layout_blocks,
        get_paddle_text_lines,
        merge_text_lines_to_blocks,
    )

    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        struct_engine, det_engine = get_layout_engines()

        is_pdf = tmp_path.lower().endswith(".pdf")
        pages_result: Dict[str, Any] = {}
        num_pages = 0

        if is_pdf:
            doc = fitz.open(tmp_path)
            num_pages = len(doc)

            for i in range(num_pages):
                page = doc[i]
                pix  = page.get_pixmap(dpi=180)
                img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    img = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)
                else:
                    img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)

                page_key = str(i + 1)
                pages_result[page_key] = _detect_page(
                    img, struct_engine, det_engine,
                    page_width_pts=page.rect.width,
                    page_height_pts=page.rect.height,
                    dpi=180,
                )
                print(f"   📄 Page {page_key}: {len(pages_result[page_key]['blocks'])} blocks detected")

            doc.close()

        else:
            # Single image
            img = cv2.imread(tmp_path)
            if img is None:
                raise HTTPException(status_code=400, detail="Cannot read image file")
            num_pages = 1
            pages_result["1"] = _detect_page(img, struct_engine, det_engine)
            print(f"   🖼️ Image: {len(pages_result['1']['blocks'])} blocks detected")

        return {
            "num_pages": num_pages,
            "pages": pages_result,
            "ocr_engine": "paddle_layout",
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


def _detect_page(
    img: np.ndarray,
    struct_engine,
    det_engine,
    page_width_pts: float = None,
    page_height_pts: float = None,
    dpi: int = 180,
) -> Dict[str, Any]:
    """
    Run layout + text detection on a single image (numpy array).

    Returns page dict:
    {
      "width_px": W, "height_px": H,
      "width_pts": W_pts, "height_pts": H_pts,  # if available
      "blocks": [...]
    }
    """
    from detection import (
        get_paddle_layout_blocks,
        get_paddle_text_lines,
        maybe_promote_image_to_table,
        merge_text_lines_to_blocks,
    )

    img_h, img_w = img.shape[:2]
    PAD = 2  # tight crop padding — keeps blocks from overlapping neighbours

    # 1. Layout detection (PP-DocLayout-S) → table / image blocks
    layout_blocks = get_paddle_layout_blocks(img, struct_engine)

    # 2. Text line detection (PP-OCRv5 DBNet) → raw text lines
    text_lines = get_paddle_text_lines(img, det_engine)

    # 3. Heuristic upgrade: image blocks that look like tables → table
    layout_blocks = maybe_promote_image_to_table(layout_blocks, text_lines)

    # 4. Merge text lines into paragraph blocks (skip table/image regions)
    text_blocks = merge_text_lines_to_blocks(text_lines, layout_blocks, img.shape)

    # 5. Build unified block list
    all_blocks: List[Dict] = []

    # --- layout blocks (table / image) ---
    for b in layout_blocks:
        x1, y1, x2, y2 = [float(v) for v in b["bbox"]]
        cx1 = max(0, x1 - PAD)
        cy1 = max(0, y1 - PAD)
        cx2 = min(img_w, x2 + PAD)
        cy2 = min(img_h, y2 + PAD)
        all_blocks.append({
            "label":      b["label"],
            "bbox":       [cx1, cy1, cx2, cy2],
            "crop_bbox":  [cx1, cy1, cx2, cy2],
            "confidence": b["confidence"],
        })

    # --- text paragraph blocks ---
    for b in text_blocks:
        x1, y1, x2, y2 = [float(v) for v in b["bbox"]]
        all_blocks.append({
            "label":      "text",
            "bbox":       [x1, y1, x2, y2],
            "crop_bbox":  [x1, y1, x2, y2],
            "confidence": 1.0,
        })

    # 6. NMS: remove text blocks that overlap heavily with layout blocks
    def _overlap_ratio_ab(a_bbox, b_bbox):
        """Fraction of a_bbox area covered by b_bbox."""
        ax1, ay1, ax2, ay2 = a_bbox
        bx1, by1, bx2, by2 = b_bbox
        ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        a_area = max(1, (ax2 - ax1) * (ay2 - ay1))
        return inter / a_area

    layout_bboxes = [b["bbox"] for b in all_blocks if b["label"] in ("table", "image")]
    kept: List[Dict] = []
    for b in all_blocks:
        if b["label"] != "text":
            kept.append(b)
            continue
        # Drop text block if 30%+ of it is covered by a layout block
        dominated = any(_overlap_ratio_ab(b["bbox"], lb) > 0.30 for lb in layout_bboxes)
        if not dominated:
            kept.append(b)
        else:
            print(f"   [NMS] dropped text block overlapping layout block")
    all_blocks = kept

    # 7. Sort blocks top-to-bottom, left-to-right
    all_blocks.sort(key=lambda b: (int(b["bbox"][1] / 20), b["bbox"][0]))

    page_info: Dict[str, Any] = {
        "width_px":  img_w,
        "height_px": img_h,
        "blocks":    all_blocks,
    }
    if page_width_pts is not None:
        page_info["width_pts"]  = page_width_pts
        page_info["height_pts"] = page_height_pts
        page_info["dpi"]        = dpi

    return page_info





if __name__ == "__main__":
    print("🚀 Starting PaddleOCR Service on port 8001...")
    uvicorn.run("paddle_service:app", host="0.0.0.0", port=8001, reload=True)
