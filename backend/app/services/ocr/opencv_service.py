"""
OpenCV Service for Text Block Detection
Implements a lightweight, in-process text segmentation pipeline.
"""
import cv2
import numpy as np
import fitz  # PyMuPDF
import os
from typing import List, Dict, Any, Tuple
from pathlib import Path

class OpenCVService:
    """
    OpenCV-based Text Block Detection
    Pipeline:
    1. Preprocessing (Gray -> Bilateral -> CLAHE -> Threshold)
    2. Pass A: Line Detection (Morphology Dilation)
    3. Pass B: Paragraph Merging (Vertical/Horizontal proximity)
    4. Table Detection (Grid Density)
    """

    def __init__(self, debug_dir: str = "debug_output"):
        self.target_dpi = 180
        self.debug_dir = debug_dir
        os.makedirs(self.debug_dir, exist_ok=True)

    def process_document(self, file_path: str, source_lang: str = "tha_Thai", job_id: str = None) -> Dict[str, Any]:
        """
        Process document to detect text blocks.
        """
        print(f"📷 OpenCV Service Processing: {file_path}")
        
        # Setup Debug Path
        debug_path = Path(self.debug_dir)
        if job_id:
            from app.config import settings
            debug_path = settings.OUTPUT_DIR / job_id / "logs" / "preprocess"
            os.makedirs(debug_path, exist_ok=True)
            print(f"🐛 Debug images will be saved to: {debug_path}")
        
        file_ext = os.path.splitext(file_path)[1].lower()
        pages_results = {}
        num_pages = 0

        if file_ext == '.pdf':
            doc = fitz.open(file_path)
            num_pages = len(doc)
            
            for i in range(num_pages):
                page = doc[i]
                # 1. Base Image Preparation (180 DPI)
                pix = page.get_pixmap(dpi=self.target_dpi)
                
                # Convert fitz Pixmap to numpy array (RGB)
                img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4: # RGBA -> BGR
                    img = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)
                else:
                    img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR) # OpenCV uses BGR
                
                # Process page
                blocks = self._process_page_image(img, page_num=i+1, debug_out_dir=debug_path)
                
                # Calculate size in points (for PDF consistency)
                width_pts = page.rect.width
                height_pts = page.rect.height
                
                print(f"   📐 Page {i+1} Geometry: rect={page.rect}, pix={pix.width}x{pix.height}")
                
                # Calculate scale factors dynamically
                # page.rect is in points (72 DPI)
                scale_x = page.rect.width / pix.width
                scale_y = page.rect.height / pix.height
                
                # Origins (Offsets)
                offset_x = page.rect.x0
                offset_y = page.rect.y0
                
                # Scale blocks from pixels back to points with offset
                scaled_blocks = self._scale_blocks(blocks, scale_x, scale_y, offset_x, offset_y)
                
                pages_results[i + 1] = {
                    "width": width_pts,
                    "height": height_pts,
                    "blocks": scaled_blocks,
                    "tables": [] # Todo: Separate tables
                }
            doc.close()

        else:
            # Image path
            img = cv2.imread(file_path)
            if img is None:
                raise ValueError(f"Could not read image: {file_path}")
            
            num_pages = 1
            height, width = img.shape[:2]
            
            # Process page
            blocks = self._process_page_image(img, page_num=1, debug_out_dir=debug_path)
            
            # For images, we need to match fitz's handling in translation_service
            # fitz.open(img_path) will create a page with dimensions based on DPI (usually 72 if not set, or image DPI)
            # We must normalize our pixel-based blocks to fitz's point-based rect.
            
            doc_img = fitz.open(file_path)
            page_img = doc_img[0]
            
            width_pts = page_img.rect.width
            height_pts = page_img.rect.height
            
            print(f"   📐 Image Page Geometry: rect={page_img.rect}, pix={width}x{height}")
            
            # Calculate scale factors
            scale_x = width_pts / width
            scale_y = height_pts / height
            
            # Scale blocks
            scaled_blocks = self._scale_blocks(blocks, scale_x, scale_y)
            
            doc_img.close()
            
            pages_results[1] = {
                "width": width_pts,
                "height": height_pts,
                "blocks": scaled_blocks,
                "tables": []
            }

        return {
            "num_pages": num_pages,
            "pages": pages_results,
            "ocr_engine": "opencv"
        }

    def _process_page_image(self, img: np.ndarray, page_num: int, debug_out_dir: Path) -> List[Dict]:
        """core layout analysis pipeline"""
        
        # --- 2. Preprocessing ---
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Debug 1: Grayscale
        if debug_out_dir:
            cv2.imwrite(str(debug_out_dir / f"page_{page_num}_1_gray.png"), gray)
        
        # Denoise: Gaussian Blur (Faster than Bilateral)
        denoised = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Debug 2: Denoised
        if debug_out_dir:
            cv2.imwrite(str(debug_out_dir / f"page_{page_num}_2_denoised_gaussian.png"), denoised)
        
        # Contrast: CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        contrast = clahe.apply(denoised)
        
        # Debug 3: CLAHE
        if debug_out_dir:
            cv2.imwrite(str(debug_out_dir / f"page_{page_num}_3_clahe.png"), contrast)
        
        # Binarize: Adaptive Threshold
        # Block Size ~31, C ~10 (User recommendation)
        binary = cv2.adaptiveThreshold(
            contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY_INV, 31, 10
        )
        
        # Debug 4: Binary
        if debug_out_dir:
            cv2.imwrite(str(debug_out_dir / f"page_{page_num}_4_binary.png"), binary)
        
        # --- 3. Segmentation Pass A: Line Detection ---
        # Dilation with wide-short kernel (35, 5 for ~180 DPI)
        kernel_line = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 5))
        dilated_lines = cv2.dilate(binary, kernel_line, iterations=1)
        
        # Debug 5: Dilated Lines
        if debug_out_dir:
             cv2.imwrite(str(debug_out_dir / f"page_{page_num}_5_dilated.png"), dilated_lines)
        
        # Find contours (Lines)
        contours_lines, _ = cv2.findContours(dilated_lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        line_boxes = []
        for cnt in contours_lines:
            x, y, w, h = cv2.boundingRect(cnt)
            # Filter noise
            if w < 10 or h < 5: continue 
            line_boxes.append({'x': x, 'y': y, 'w': w, 'h': h, 'x2': x+w, 'y2': y+h})
            
        # Draw debug lines
        if debug_out_dir:
            debug_lines_img = img.copy()
            for b in line_boxes:
                cv2.rectangle(debug_lines_img, (b['x'], b['y']), (b['x2'], b['y2']), (0, 255, 0), 2)
            cv2.imwrite(str(debug_out_dir / f"page_{page_num}_6_lines_detected.png"), debug_lines_img)
        
        # --- 3. Segmentation Pass B: Paragraph Merging ---
        # Sort by Y then X (Top to Bottom, Left to Right)
        # Round Y to nearest 10px to group items in same "row" for sorting
        line_boxes.sort(key=lambda b: (int(b['y']/10), b['x']))
        
        blocks = []
        if not line_boxes:
            return blocks
            
        current_block = line_boxes[0]
        
        # Calculate median line height for dynamic gap threshold
        lines_heights = [b['h'] for b in line_boxes]
        median_h = np.median(lines_heights) if lines_heights else 20
        max_gap = 0.5 * median_h # Reduced from 0.8 to 0.5 to avoid merging distant blocks
        
        for next_box in line_boxes[1:]:
            # Check vertical gap
            gap = next_box['y'] - current_block['y2']
            
            # Check horizontal alignment (roughly overlap in X)
            # Vertical proximity check
            is_vertical_close = gap < max_gap
            
            # Horizontal overlap check
            x_overlap = max(0, min(current_block['x2'], next_box['x2']) - max(current_block['x'], next_box['x']))
            is_horizontal_aligned = x_overlap > (min(current_block['w'], next_box['w']) * 0.5) # >50% width overlap
            
            # Height similarity check (Don't merge headers with body text)
            h_ratio = min(current_block['h'], next_box['h']) / max(current_block['h'], next_box['h'])
            is_height_similar = h_ratio > 0.5
            
            if is_vertical_close and is_horizontal_aligned and is_height_similar:
                # Merge
                current_block['x'] = min(current_block['x'], next_box['x'])
                current_block['y'] = min(current_block['y'], next_box['y'])
                current_block['x2'] = max(current_block['x2'], next_box['x2'])
                current_block['y2'] = max(current_block['y2'], next_box['y2'])
                current_block['w'] = current_block['x2'] - current_block['x']
                current_block['h'] = current_block['y2'] - current_block['y']
            else:
                blocks.append(current_block)
                current_block = next_box
        
        blocks.append(current_block) # Append last block
        
        # Format output blocks
        final_blocks = []
        debug_blocks_img = img.copy()
        
        for i, b in enumerate(blocks):
            # Original BBox (Tight)
            x1, y1 = b['x'], b['y']
            x2, y2 = b['x2'], b['y2']

            # [NEW] Text Validation: Check density of small contours (letters)
            # A valid text block must have multiple small components (letters)
            # If a block has 0-1 contours, it is likely a box or line.
            
            # Crop binary image for this block
            block_binary = binary[y1:y2, x1:x2]
            if block_binary.size == 0: continue
            
            # Find contours inside this block
            block_cnts, _ = cv2.findContours(block_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filter noise contours from count
            valid_chars = 0
            for c in block_cnts:
                cx, cy, cw, ch = cv2.boundingRect(c)
                if cw > 2 and ch > 5: # Minimal char size
                    valid_chars += 1
            
            # Heuristic:
            # - If block is large but has few chars -> Graphic/Box
            # - Text usually has many chars
            if valid_chars < 2:
                # Allow if it's a very small block (maybe a page number "1")
                # But if height > 20 (approx line height), it should have more parts
                if b['h'] > 20:
                     continue
            
            # Crop BBox (Padded for OCR)
            pad_x = 12
            pad_y = 12
            
            cx1 = max(0, x1 - pad_x)
            cy1 = max(0, y1 - pad_y)
            cx2 = min(img.shape[1], x2 + pad_x)
            cy2 = min(img.shape[0], y2 + pad_y)
            
            # Draw debug (Red = Tight, Blue = Crop)
            cv2.rectangle(debug_blocks_img, (cx1, cy1), (cx2, cy2), (255, 0, 0), 1) # Blue: Crop
            cv2.rectangle(debug_blocks_img, (x1, y1), (x2, y2), (0, 0, 255), 2)     # Red: Tight
            cv2.putText(debug_blocks_img, str(i), (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)
            
            final_blocks.append({
                "text": "", 
                "bbox": { # Tight bbox for rendering
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2
                },
                "crop_bbox": { # Padded bbox for OCR
                    "x1": cx1,
                    "y1": cy1,
                    "x2": cx2,
                    "y2": cy2
                },
                "label": "text",
                "confidence": 1.0
            })

        if debug_out_dir:
            cv2.imwrite(str(debug_out_dir / f"page_{page_num}_7_blocks_merged.png"), debug_blocks_img)
        
        return final_blocks

    def _scale_blocks(self, blocks: List[Dict], scale_x: float, scale_y: float, offset_x: float = 0, offset_y: float = 0) -> List[Dict]:
        """Scale bounding boxes and apply offset"""
        scaled = []
        for b in blocks:
            new_b = b.copy()
            
            # Scale
            sx1 = (b["bbox"]["x1"] * scale_x) + offset_x
            sy1 = (b["bbox"]["y1"] * scale_y) + offset_y
            sx2 = (b["bbox"]["x2"] * scale_x) + offset_x
            sy2 = (b["bbox"]["y2"] * scale_y) + offset_y
            
            # Normalize (Ensure 1 < 2)
            new_b["bbox"] = {
                "x1": min(sx1, sx2),
                "y1": min(sy1, sy2),
                "x2": max(sx1, sx2),
                "y2": max(sy1, sy2)
            }
            
            # Scale crop_bbox if exists
            if "crop_bbox" in b:
                cx1 = (b["crop_bbox"]["x1"] * scale_x) + offset_x
                cy1 = (b["crop_bbox"]["y1"] * scale_y) + offset_y
                cx2 = (b["crop_bbox"]["x2"] * scale_x) + offset_x
                cy2 = (b["crop_bbox"]["y2"] * scale_y) + offset_y
                
                new_b["crop_bbox"] = {
                    "x1": min(cx1, cx2),
                    "y1": min(cy1, cy2),
                    "x2": max(cx2, cx2), # Potential typo here: cx2, cx2 -> fixed to min/max
                    "y2": max(cy2, cy2)
                }
                # Fix typo above: cx2 is max, so compare cx1, cx2
                new_b["crop_bbox"] = {
                    "x1": min(cx1, cx2),
                    "y1": min(cy1, cy2),
                    "x2": max(cx1, cx2),
                    "y2": max(cy1, cy2)
                }

            scaled.append(new_b)
        return scaled
