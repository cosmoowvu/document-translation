"""
Bounding Box Utilities for OCR layout blocks.
"""
from typing import List, Dict

def merge_overlapping_blocks(blocks: List[Dict], margin: float = 0.0) -> List[Dict]:
    """
    Merge blocks that intersect with each other to guarantee no overlapping bounding boxes.
    Uses an iterative union-find approach.
    
    Args:
        blocks: List of block dictionaries, each containing 'bbox' dict with x1, y1, x2, y2.
        margin: Extra padding around bounding boxes when checking intersection.
    """
    if not blocks:
        return []
        
    def check_intersection(b1: Dict, b2: Dict) -> bool:
        # Check if b1 and b2 intersect
        x_left = max(b1['x1'] - margin, b2['x1'] - margin)
        y_top = max(b1['y1'] - margin, b2['y1'] - margin)
        x_right = min(b1['x2'] + margin, b2['x2'] + margin)
        y_bottom = min(b1['y2'] + margin, b2['y2'] + margin)
        
        # If intersection area is > 0
        if x_right > x_left and y_bottom > y_top:
            return True
        return False
        
    # Build disjoint sets (Union-Find)
    parent = {i: i for i in range(len(blocks))}
    
    def find(i):
        if parent[i] == i:
            return i
        parent[i] = find(parent[i])
        return parent[i]
        
    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    # Extract simplified rects
    rects = []
    for b in blocks:
        bb = b.get("bbox", {})
        # ensure valid floats just in case
        rects.append({
            "x1": float(bb.get("x1", 0)),
            "y1": float(bb.get("y1", 0)),
            "x2": float(bb.get("x2", 0)),
            "y2": float(bb.get("y2", 0)),
        })
        
    # Check all pairs for intersection
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if check_intersection(rects[i], rects[j]):
                union(i, j)
                
    # Group blocks by root
    groups = {}
    for i in range(len(blocks)):
        root = find(i)
        if root not in groups:
            groups[root] = []
        groups[root].append(blocks[i])
        
    merged_blocks = []
    
    # Process each group into a single merged block
    for root_idx, group in groups.items():
        if len(group) == 1:
            merged_blocks.append(group[0])
            continue
            
        # Merge bounding box
        min_x1 = min(b.get("bbox", {}).get("x1", 0) for b in group)
        min_y1 = min(b.get("bbox", {}).get("y1", 0) for b in group)
        max_x2 = max(b.get("bbox", {}).get("x2", 0) for b in group)
        max_y2 = max(b.get("bbox", {}).get("y2", 0) for b in group)
        
        merged_bbox = {"x1": min_x1, "y1": min_y1, "x2": max_x2, "y2": max_y2}
        
        # Merge crop_bbox if any block has it
        has_crop = any("crop_bbox" in b for b in group)
        crop_bbox = None
        if has_crop:
            c_min_x1 = min(b.get("crop_bbox", b.get("bbox", {})).get("x1", 0) for b in group)
            c_min_y1 = min(b.get("crop_bbox", b.get("bbox", {})).get("y1", 0) for b in group)
            c_max_x2 = max(b.get("crop_bbox", b.get("bbox", {})).get("x2", 0) for b in group)
            c_max_y2 = max(b.get("crop_bbox", b.get("bbox", {})).get("y2", 0) for b in group)
            crop_bbox = {"x1": c_min_x1, "y1": c_min_y1, "x2": c_max_x2, "y2": c_max_y2}
            
        # Determine label priority: table > image > text
        labels = [b.get("label", "text") for b in group]
        if "table" in labels:
            final_label = "table"
        elif "image" in labels:
            final_label = "image"
        else:
            final_label = "text"
            
        # Extract highest confidence
        confidence = max((b.get("confidence", 1.0) for b in group), default=1.0)
            
        merged_block = {
            "text": "",
            "label": final_label,
            "bbox": merged_bbox,
            "confidence": confidence
        }
        
        if crop_bbox:
            merged_block["crop_bbox"] = crop_bbox
            
        merged_blocks.append(merged_block)
        
    return merged_blocks
