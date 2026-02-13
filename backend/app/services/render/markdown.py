
from typing import Dict, Any

def export_to_markdown(doc_result: Dict[str, Any], output_path: str):
    """Generate Markdown file from document blocks"""
    with open(output_path, "w", encoding="utf-8") as f:
        for page_no in range(1, doc_result["num_pages"] + 1):
            page_data = doc_result["pages"].get(page_no) or doc_result["pages"].get(str(page_no))
            if not page_data: continue
            
            f.write(f"## Page {page_no}\n\n")
            
            # Blocks are already sorted by Y then X in OpenCVService/Typhoon
            blocks = page_data.get("blocks", [])
            for block in blocks:
                text = block.get("text", "").strip()
                if text:
                    f.write(f"{text}\n\n")
            
            f.write("---\n\n")
    print(f"   📝 Saved Markdown to {output_path}")
