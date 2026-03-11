"""
hybrid_layout_service.py
Combines the precision of OpenCV layout parsing with the robustness of PaddleOCR.
paddle_service provides fallback blocks when OpenCV misses them.
"""
from typing import Dict, Any, List
import copy
from .opencv_service import OpenCVService
from .paddle_layout_service import PaddleLayoutService


class HybridLayoutService:
    """
    Runs both OpenCV and Paddle Layout Analysis.
    Merges the results: taking OpenCV as the primary source of truth,
    and appending any blocks found by Paddle that do not intersect with OpenCV blocks.
    """
    
    def __init__(self):
        self._opencv = OpenCVService()
        self._paddle = PaddleLayoutService()

    def process_document(
        self,
        file_path: str,
        source_lang: str = "tha_Thai",
        job_id: str = None,
        job_status: Dict = None,
    ) -> Dict[str, Any]:
        """
        Processes document using OpenCV and Paddle, then merges the blocks.
        """
        print(f"🔄 Hybrid Layout Service: Starting OpenCV Processing...")
        # 1. Run OpenCV (Primary)
        # Note: We assume opencv_service has been updated to include _apply_multipage_corrections
        cv_result = self._opencv.process_document(file_path, source_lang, job_id, job_status)
        
        # Check cancellation
        if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
            return cv_result

        print(f"🔄 Hybrid Layout Service: Starting PaddleOCR Fallback Processing...")
        # 2. Run Paddle (Fallback)
        try:
            paddle_result = self._paddle.process_document(file_path, source_lang, job_id, job_status)
        except Exception as e:
            print(f"   ⚠️ Paddle Layout failed, falling back to pure OpenCV. Error: {e}")
            return cv_result

        if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
            return cv_result

        # 3. Merge Results Page by Page
        merged_result = copy.deepcopy(cv_result)
        merged_result["ocr_engine"] = "hybrid"
        
        total_paddles_merged = 0

        for page_num_key, cv_page_data in merged_result.get("pages", {}).items():
            paddle_page_data = paddle_result.get("pages", {}).get(str(page_num_key))
            if not paddle_page_data:
                continue
                
            cv_blocks = cv_page_data.get("blocks", [])
            paddle_blocks = paddle_page_data.get("blocks", [])
            
            blocks_to_add = []
            
            for p_block in paddle_blocks:
                p_bbox = p_block.get("bbox")
                if not p_bbox: continue
                
                # Check intersection with ALL OpenCV blocks on this page
                is_intersecting = False
                for cv_block in cv_blocks:
                    cv_bbox = cv_block.get("bbox")
                    if not cv_bbox: continue
                    
                    if self._check_intersection(p_bbox, cv_bbox):
                        is_intersecting = True
                        break
                
                # If Paddle block doesn't touch any OpenCV block, it's a MISSING block! Add it.
                if not is_intersecting:
                    # Tag it so we know it came from fallback
                    p_block["_source"] = "paddle_fallback"
                    blocks_to_add.append(p_block)
            
            if blocks_to_add:
                print(f"   ➕ Page {page_num_key}: Merged {len(blocks_to_add)} missing blocks from Paddle")
                cv_blocks.extend(blocks_to_add)
                total_paddles_merged += len(blocks_to_add)
                
                # Re-sort blocks top-to-bottom, left-to-right (Optional but good for reading order)
                # Group by rough Y position (e.g. 15 points)
                cv_page_data["blocks"] = sorted(
                    cv_blocks, 
                    key=lambda b: (int(b.get("bbox", {}).get("y1", 0) / 15), b.get("bbox", {}).get("x1", 0))
                )

        print(f"✅ Hybrid Layout Complete. Recovered {total_paddles_merged} blocks total.")
        return merged_result

    def _check_intersection(self, bbox1: Dict[str, float], bbox2: Dict[str, float], overlap_threshold: float = 0.1) -> bool:
        """
        Checks if two bounding boxes intersect significantly.
        bbox format: {"x1": float, "y1": float, "x2": float, "y2": float}
        overlap_threshold: minimum intersection area over the smaller bbox area to be considered an intersection.
        """
        # Calculate Intersection
        x_left = max(bbox1['x1'], bbox2['x1'])
        y_top = max(bbox1['y1'], bbox2['y1'])
        x_right = min(bbox1['x2'], bbox2['x2'])
        y_bottom = min(bbox1['y2'], bbox2['y2'])

        if x_right < x_left or y_bottom < y_top:
            return False  # No intersection

        intersection_area = (x_right - x_left) * (y_bottom - y_top)

        # Calculate Areas
        area1 = (bbox1['x2'] - bbox1['x1']) * (bbox1['y2'] - bbox1['y1'])
        area2 = (bbox2['x2'] - bbox2['x1']) * (bbox2['y2'] - bbox2['y1'])

        # Protect against division by zero (e.g., zero-width/height line bboxes)
        if area1 <= 0 or area2 <= 0:
             return False

        min_area = min(area1, area2)
        
        # If intersection area is relatively large enough
        return (intersection_area / min_area) > overlap_threshold
