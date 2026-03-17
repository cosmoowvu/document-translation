"""
paddle_layout_service.py
HTTP client that calls paddle_service /detect endpoint.

Provides the same interface as OpenCVService so that ocr_pipeline.py
can swap engines without any changes to the crop/OCR flow.

The /detect endpoint returns block metadata in PIXEL coordinates.
This service scales them to PDF points so the rest of the pipeline
(fitz-based cropping) works identically.
"""
import os
from pathlib import Path
from typing import Dict, Any, List

import fitz          # PyMuPDF
import requests

PADDLE_SERVICE_URL = os.getenv("PADDLE_SERVICE_URL", "http://localhost:8001")
DETECT_ENDPOINT    = f"{PADDLE_SERVICE_URL}/detect"
TIMEOUT_SEC        = 120   # layout detection can be slow on CPU


class PaddleLayoutService:
    """
    Calls paddle_service /detect to obtain block layout
    (text / table / image) and returns a page dict compatible
    with the rest of the OCR pipeline.
    """

    def process_document(
        self,
        file_path: str,
        source_lang: str = "tha_Thai",
        job_id: str = None,
        job_status: Dict = None,
    ) -> Dict[str, Any]:
        """
        Send the file to paddle_service /detect and convert the response
        to the internal format used by ocr_pipeline.py.

        Internal format per page:
        {
          "width":  <float, points>,
          "height": <float, points>,
          "blocks": [
            {
              "text":      "",
              "label":     "text" | "table" | "image",
              "bbox":      {"x1", "y1", "x2", "y2"},   # points
              "crop_bbox": {"x1", "y1", "x2", "y2"},   # points
              "confidence": float
            }, ...
          ],
          "tables": []
        }
        """
        print(f"🔷 PaddleLayoutService: sending {os.path.basename(file_path)} to {DETECT_ENDPOINT}")

        # Send file to paddle_service
        with open(file_path, "rb") as f:
            try:
                resp = requests.post(
                    DETECT_ENDPOINT,
                    files={"file": (os.path.basename(file_path), f)},
                    timeout=TIMEOUT_SEC,
                )
            except requests.exceptions.ConnectionError as e:
                raise RuntimeError(
                    f"Cannot connect to paddle_service at {PADDLE_SERVICE_URL}. "
                    f"Make sure 'uvicorn paddle_service:app --port 8001' is running. "
                    f"Detail: {e}"
                )

        if resp.status_code != 200:
            raise RuntimeError(
                f"paddle_service /detect returned {resp.status_code}: {resp.text[:300]}"
            )

        detect_result = resp.json()
        num_pages     = detect_result.get("num_pages", 1)
        raw_pages     = detect_result.get("pages", {})

        # ------------------------------------------------------------------
        # Get page dimensions in PDF points for accurate coordinate scaling.
        # We open the file with fitz to get the authoritative point sizes.
        # ------------------------------------------------------------------
        fitz_doc          = fitz.open(file_path)
        fitz_pages_count  = len(fitz_doc)

        pages_result: Dict[str, Any] = {}

        for page_key, page_data in raw_pages.items():
            page_idx = int(page_key) - 1
            if page_idx >= fitz_pages_count:
                continue

            # Check cancellation
            if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
                print(f"      ⛔ Job {job_id} cancelled during PaddleLayout conversion")
                break

            fitz_page     = fitz_doc[page_idx]
            width_pts     = fitz_page.rect.width
            height_pts    = fitz_page.rect.height

            # Pixel dimensions from paddle_service
            img_w_px  = page_data.get("width_px",  1)
            img_h_px  = page_data.get("height_px", 1)

            # Scale factors: pixels → points
            scale_x = width_pts  / img_w_px
            scale_y = height_pts / img_h_px

            print(f"   📄 Page {page_key}: {img_w_px}x{img_h_px}px → "
                  f"{width_pts:.1f}x{height_pts:.1f}pts  "
                  f"(scale {scale_x:.4f}, {scale_y:.4f})")

            raw_blocks = page_data.get("blocks", [])
            converted_blocks: List[Dict] = []

            for b in raw_blocks:
                label      = b.get("label", "text")
                confidence = b.get("confidence", 1.0)

                bbox_px      = b.get("bbox",      [0, 0, 0, 0])
                crop_bbox_px = b.get("crop_bbox", bbox_px)

                converted_blocks.append({
                    "text":       "",
                    "label":      label,
                    "bbox":       self._to_pts(bbox_px, scale_x, scale_y),
                    "crop_bbox":  self._to_pts(crop_bbox_px, scale_x, scale_y),
                    "confidence": confidence,
                })

            pages_result[page_key] = {
                "width":  width_pts,
                "height": height_pts,
                "blocks": converted_blocks,
                "tables": [],
            }

            label_counts = {}
            for b in converted_blocks:
                label_counts[b["label"]] = label_counts.get(b["label"], 0) + 1
            print(f"      → {len(converted_blocks)} blocks: {label_counts}")

        fitz_doc.close()

        return {
            "num_pages":  num_pages,
            "pages":      pages_result,
            "ocr_engine": "paddle_layout",
        }

    @staticmethod
    def _to_pts(bbox_px_list, scale_x: float, scale_y: float) -> dict:
        """Convert pixel bbox [x1,y1,x2,y2] to PDF points dict."""
        x1, y1, x2, y2 = bbox_px_list
        return {
            "x1": float(x1) * scale_x,
            "y1": float(y1) * scale_y,
            "x2": float(x2) * scale_x,
            "y2": float(y2) * scale_y,
        }
