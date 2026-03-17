import numpy as np
import statistics
from typing import List, Dict


# Per-label confidence thresholds.
# PP-DocLayout-S classes: text, title, table, figure, figure_caption,
#   table_caption, isolate_formula, formula_caption, abandon, header, footer,
#   paragraph, image, seal
# PicoDet-S_layout_17cls (backward compat): same table/figure names
_SCORE_THRESH = {
    "table":            0.45,   # lowered: PP-DocLayout is better at tables
    "figure":           0.50,
    "image":            0.50,
    "seal":             0.55,
    "chart":            0.50,
    # Everything else defaults to 0.45
}

# Classes that map to "text" label (DBNet handles these, layout model skips them)
_TEXT_CLASSES = {
    # PP-DocLayout-S
    "text", "title", "paragraph", "header", "footer",
    "figure_caption", "table_caption", "formula_caption",
    "isolate_formula", "abandon",
    # PicoDet-S_layout_17cls (backward compat)
    "paragraph_title", "doc_title", "reference",
    "formula", "algorithm", "figure_footnote", "table_footnote",
    "equation", "code_block", "table_title", "figure_title",
}

# Classes that map to "image" label
_IMAGE_CLASSES = {
    # PP-DocLayout-S
    "figure", "image", "chart",
    # PicoDet-S_layout_17cls (backward compat)
    "seal",
}

# Classes that map to "table" label
_TABLE_CLASSES = {"table"}


def get_paddle_layout_blocks(img: np.ndarray, struct_engine) -> List[Dict]:
    """
    Run LayoutDetection (PicoDet-S_layout_17cls) to find tables, images.
    Returns: [{"bbox": [x1,y1,x2,y2], "label": "table"|"image", "confidence": float}]
    """
    layout_blocks = []
    img_h, img_w = img.shape[:2]
    img_area = img_h * img_w
    raw_count = 0

    try:
        results = struct_engine.predict(img)
        for res_idx, res in enumerate(results):
            # ── DEBUG: inspect result structure once ──────────────────────
            # if res_idx == 0:
            #     print(f"   [LAYOUT DEBUG] result type: {type(res)}")
            #     try:
            #         boxes_sample = res.get("boxes", [])
            #         print(f"   [LAYOUT DEBUG] boxes count={len(boxes_sample)}, sample[0]={boxes_sample[0] if boxes_sample else 'empty'}")
            #     except Exception:
            #         pass
            # ─────────────────────────────────────────────────────────────

            # DetResult is a dict: res["boxes"] → list of box dicts
            # Each box: {"label": str, "coordinate": [x1,y1,x2,y2], "score": float, "cls_id": int}
            boxes = res.get("boxes", []) if hasattr(res, "get") else []

            for box in boxes:
                # Key is "label" NOT "cls_name" (per PaddleX DetResult source)
                if isinstance(box, dict):
                    cls_name = str(box.get("label", box.get("cls_name", ""))).lower()
                    coord    = box.get("coordinate", box.get("bbox", []))
                    score    = float(box.get("score", 1.0))
                else:
                    cls_name = str(getattr(box, "label", getattr(box, "cls_name", ""))).lower()
                    coord    = getattr(box, "coordinate", getattr(box, "bbox", []))
                    score    = float(getattr(box, "score", 1.0))

                raw_count += 1
                # print(f"   [LAYOUT RAW] cls={cls_name} score={score:.3f} coord={coord}")

                if not coord or len(coord) not in (4, 8):
                    continue

                # Normalize to 4-point bbox if rotated (8 points)
                if len(coord) == 8:
                    xs = coord[0::2]; ys = coord[1::2]
                    coord = [min(xs), min(ys), max(xs), max(ys)]

                thresh = _SCORE_THRESH.get(cls_name, 0.50)
                if score < thresh:
                    # print(f"   [LAYOUT SKIP] {cls_name} score {score:.3f} < {thresh}")
                    continue

                x1, y1, x2, y2 = coord
                b_area = (x2 - x1) * (y2 - y1)

                if cls_name in _TABLE_CLASSES:
                    label = "table"
                elif cls_name in _IMAGE_CLASSES:
                    label = "image"
                else:
                    continue

                layout_blocks.append({
                    "bbox": [x1, y1, x2, y2],
                    "label": label,
                    "confidence": score,
                })


        print(f"   [LAYOUT] {raw_count} raw boxes → {len(layout_blocks)} accepted layout blocks")
    except Exception as e:
        print(f"   ⚠️ Layout predict error: {e}")
        import traceback
        traceback.print_exc()

    return layout_blocks





def get_paddle_text_lines(img: np.ndarray, ocr_det_engine) -> List[Dict]:
    """
    Run DBNet Text Detection to find raw text line bounding boxes.
    Returns: [{"bbox": [x1,y1,x2,y2], "label": "text", "x", "y", "x2", "y2", "w", "h"}]
    """
    text_lines = []
    try:
        results = ocr_det_engine.predict(img)
        for res in results:
            # PP-OCRv4 may return an object (attribute access) or dict-style
            if hasattr(res, "dt_polys"):
                polys = res.dt_polys
            elif hasattr(res, "get"):
                polys = res.get("dt_polys", None)
            else:
                polys = None

            # Safe empty check — avoids ValueError on numpy arrays
            if polys is None:
                continue
            try:
                n = len(polys)
            except Exception:
                continue
            if n == 0:
                continue

            for poly in polys:
                if poly is None or len(poly) == 0:
                    continue

                pts = np.array(poly, dtype=np.float32)
                if pts.ndim >= 2 and pts.shape[0] >= 4:
                    x1 = float(np.min(pts[:, 0]))
                    x2 = float(np.max(pts[:, 0]))
                    y1 = float(np.min(pts[:, 1]))
                    y2 = float(np.max(pts[:, 1]))
                else:
                    continue

                w, h = x2 - x1, y2 - y1
                if w < 5 or h < 5:
                    continue

                text_lines.append({
                    "bbox": [x1, y1, x2, y2],
                    "label": "text",
                    "x": x1, "y": y1, "x2": x2, "y2": y2,
                    "w": w, "h": h,
                })
    except Exception as e:
        print(f"   ⚠️ Text line detection error: {e}")
        import traceback
        traceback.print_exc()

    return text_lines


def maybe_promote_image_to_table(
    layout_blocks: List[Dict],
    text_lines: List[Dict],
    min_lines: int = 4,
    min_cols: int = 2,
    min_multicol_rows: int = 2,
) -> List[Dict]:
    """
    Heuristic re-classifier: promote 'image' blocks to 'table' when they
    contain multiple text lines arranged in a grid pattern.

    Layout models (PP-DocLayout, PicoDet) often mis-label worksheets /
    grid-tables as 'figure' or 'image' because they were trained on
    academic paper datasets where tables have clear borders.

    Logic:
      For each block labeled 'image':
        1. Collect DBNet text lines whose center falls inside the block.
        2. If count < min_lines  →  keep as image.
        3. Cluster lines into rows by y-center proximity.
        4. Count rows where there are >= min_cols separate text lines (columns).
        5. If >= min_multicol_rows such rows exist  →  promote to 'table'.
    """
    result = []
    for blk in layout_blocks:
        if blk["label"] != "image":
            result.append(blk)
            continue

        lx1, ly1, lx2, ly2 = blk["bbox"]

        # Step 1: Text lines whose center lies inside this block
        inside = []
        for line in text_lines:
            tx1, ty1, tx2, ty2 = line["bbox"]
            cx = (tx1 + tx2) / 2
            cy = (ty1 + ty2) / 2
            if lx1 <= cx <= lx2 and ly1 <= cy <= ly2:
                inside.append(line)

        if len(inside) < min_lines:
            result.append(blk)
            continue

        # Step 2: Cluster into rows by y-center with tolerance = 70% median height
        heights  = [l["h"] for l in inside]
        median_h = statistics.median(heights) if heights else 20
        row_tol  = median_h * 0.7

        inside.sort(key=lambda l: l["y"])
        rows: List[List[Dict]] = []
        cur_row = [inside[0]]
        for line in inside[1:]:
            if abs(line["y"] - cur_row[-1]["y"]) <= row_tol:
                cur_row.append(line)
            else:
                rows.append(cur_row)
                cur_row = [line]
        rows.append(cur_row)

        # Step 3: Count multi-column rows
        multicol_rows = sum(1 for row in rows if len(row) >= min_cols)

        if multicol_rows >= min_multicol_rows:
            print(
                f"   [HEURISTIC] image→table promotion: "
                f"{len(inside)} lines, {len(rows)} rows, "
                f"{multicol_rows} multi-col rows "
                f"bbox=[{lx1:.0f},{ly1:.0f},{lx2:.0f},{ly2:.0f}]"
            )
            blk = dict(blk)
            blk["label"] = "table"

        result.append(blk)

    return result


def merge_text_lines_to_blocks(
    text_lines: List[Dict],
    layout_blocks: List[Dict],
    img_shape: tuple,
) -> List[Dict]:
    """
    Merge raw DBNet text lines into paragraph-level blocks.
    Lines that overlap significantly with a table/image layout block are skipped.

    Fixes applied:
    - Sort by (y_center // line_height_band) so slightly staggered lines on the
      same row are grouped correctly before column ordering.
    - Gap tolerance raised to 2.0× median_h (was 0.8×) to keep paragraph lines
      together even when spacing is generous.
    - Short-last-line heuristic tightened so it doesn't prematurely cut paragraphs.
    - Blocks in clearly separate horizontal columns are NOT merged.
    """
    if not text_lines:
        return []

    # Build exclusion zones from table/image blocks
    exclude_bboxes = [b["bbox"] for b in layout_blocks]  # [[x1,y1,x2,y2], ...]

    def _overlap_ratio(line_bbox, excl_bbox):
        lx1, ly1, lx2, ly2 = line_bbox
        ex1, ey1, ex2, ey2 = excl_bbox
        ix1 = max(lx1, ex1); iy1 = max(ly1, ey1)
        ix2 = min(lx2, ex2); iy2 = min(ly2, ey2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        return inter / max(1, (lx2 - lx1) * (ly2 - ly1))

    # Remove lines dominated by table/image regions
    filtered = [
        ln for ln in text_lines
        if not any(_overlap_ratio(ln["bbox"], ex) > 0.5 for ex in exclude_bboxes)
    ]
    if not filtered:
        return []

    # ── Compute typical line metrics ──────────────────────────────────────
    heights  = [b["h"] for b in filtered]
    median_h = statistics.median(heights) if heights else 20
    band     = max(int(median_h * 0.6), 4)   # vertical bucket size for row grouping

    # Sort: bucket by row band first, then left-to-right within the row
    filtered.sort(key=lambda b: (int((b["y"] + b["h"] * 0.5) / band), b["x"]))

    # Gap tolerance: paragraph lines can be up to 2× the median line height apart
    max_gap = median_h * 2.0

    # ── Merge consecutive lines into paragraph blocks ─────────────────────
    img_h, img_w = img_shape[:2]
    blocks: List[Dict] = []
    cur = dict(filtered[0])

    for nxt in filtered[1:]:
        gap       = nxt["y"] - cur["y2"]           # vertical gap between lines
        y_close   = gap < max_gap and gap > -median_h  # allow slight overlap

        # Horizontal overlap between the two lines
        x_overlap = max(0, min(cur["x2"], nxt["x2"]) - max(cur["x"], nxt["x"]))
        narrower  = min(cur["w"], nxt["w"])
        h_aligned = x_overlap > narrower * 0.25    # at least 25% columns overlap

        # Column separation: if both lines are wide and they don't overlap at all,
        # they are likely in different columns → do NOT merge
        both_wide  = cur["w"] > img_w * 0.3 and nxt["w"] > img_w * 0.3
        no_overlap = x_overlap <= 0
        diff_cols  = both_wide and no_overlap

        # Height similarity (ignore very different font sizes)
        h_ratio = min(cur["h"], nxt["h"]) / max(max(cur["h"], nxt["h"]), 1)
        h_sim   = h_ratio > 0.4

        should_merge = (
            y_close
            and h_aligned
            and h_sim
            and not diff_cols
        )

        if should_merge:
            cur["x"]   = min(cur["x"],  nxt["x"])
            cur["y"]   = min(cur["y"],  nxt["y"])
            cur["x2"]  = max(cur["x2"], nxt["x2"])
            cur["y2"]  = max(cur["y2"], nxt["y2"])
            cur["w"]   = cur["x2"] - cur["x"]
            cur["h"]   = cur["y2"] - cur["y"]
            cur["bbox"] = [cur["x"], cur["y"], cur["x2"], cur["y2"]]
        else:
            blocks.append(cur)
            cur = dict(nxt)

    blocks.append(cur)

    # ── Add padding and minimum-size filter ──────────────────────────────
    pad = 3   # keep tight — large padding causes overlaps between adjacent blocks
    result = []
    for b in blocks:
        x1 = max(0,     b["x"]  - pad)
        y1 = max(0,     b["y"]  - pad)
        x2 = min(img_w, b["x2"] + pad)
        y2 = min(img_h, b["y2"] + pad)
        w, h = x2 - x1, y2 - y1

        if w < 15 or h < 10:
            continue

        result.append({
            "bbox":  [x1, y1, x2, y2],
            "label": "text",
            "x": x1, "y": y1, "x2": x2, "y2": y2,
            "w": w,   "h": h,
            "confidence": 1.0,
        })

    print(f"   [MERGE] {len(filtered)} text lines → {len(result)} text blocks  "
          f"(median_h={median_h:.1f}, max_gap={max_gap:.1f})")
    return result


