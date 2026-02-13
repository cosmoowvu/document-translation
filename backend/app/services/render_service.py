"""
Render Service
วาดข้อความแปลลงบน canvas ตาม bounding box
(Refactored: uses font_service and text_processor)
"""
import os
from typing import Dict, Any, List
from PIL import Image, ImageDraw

from app.config import settings
from app.services.font_service import font_service
from app.services.text_processor import is_ocr_flow_mode

# Import new modules
from app.services.render.table_renderer import parse_html_table, draw_table
from app.services.render.markdown import export_to_markdown
from app.services.render.overlay import render_page_overlay
from app.services.render.flow import render_page_flow


class RenderService:
    def __init__(self):
        self.dpi = settings.DPI
        self.font_service = font_service
    
    def render_page_flow(self, page_data: Dict, page_no: int, 
                         base_font_size: int = 24,
                         margins: Dict = None) -> List[Image.Image]:
        """
        Render หน้าแบบ flow-based สำหรับ OCR images
        Delegates to app.services.render.flow
        """
        return render_page_flow(
            page_data=page_data, 
            page_no=page_no, 
            dpi=self.dpi, 
            font_service=self.font_service, 
            base_font_size=base_font_size, 
            margins=margins
        )

    def render_page(self, page_data: Dict, page_no: int) -> Image.Image:
        """
        Render หน้าเดียว (blocks + tables) - Overlay Mode
        Delegates to app.services.render.overlay
        """
        return render_page_overlay(
            page_data=page_data, 
            page_no=page_no, 
            dpi=self.dpi, 
            font_service=self.font_service
        )
    
    def _parse_html_table(self, html_text: str) -> Dict:
        """Wrapper for utils.parse_html_table"""
        return parse_html_table(html_text)
    
    def _draw_table(self, draw, table: Dict, scale: float, font_multiplier: float = 1.0) -> int:
        """Wrapper for utils.draw_table"""
        return draw_table(draw, table, scale, self.font_service, font_multiplier)
    
    def render_document(self, job_id: str, doc_result: Dict[str, Any]) -> str:
        """Render เอกสารทั้งหมดและบันทึก พร้อม export หลายรูปแบบ"""
        from app.services.export_service import export_service
        
        output_dir = settings.OUTPUT_DIR / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        
        images = []
        
        for page_no in range(1, doc_result["num_pages"] + 1):
            page_data = doc_result["pages"].get(page_no) or doc_result["pages"].get(str(page_no))
            
            if page_data is None:
                print(f"   ⚠️ Render: Page {page_no} not found, skipping...")
                continue
            
            # Logic for Render Mode selection
            render_mode_param = doc_result.get("render_mode", "auto")
            is_flow_requested = render_mode_param == "flow"
            
            # [FIX] If we have a background image, we MUST use render_page (Overlay)
            # to preserve the background. Flow mode discards the background.
            has_bg_image = "image_path" in page_data and os.path.exists(page_data["image_path"])
            
            if has_bg_image:
                 print(f"   🖼️ Background image found, forcing Overlay Mode (Smart Inpaint)")
                 is_flow_requested = False
            
            if is_flow_requested or (is_ocr_flow_mode(page_data) and not has_bg_image):
                print(f"   📄 Page {page_no}: Using flow rendering mode (Flow Requested={is_flow_requested})")
                page_images = self.render_page_flow(page_data, page_no)
                
                for flow_idx, canvas in enumerate(page_images):
                    if len(page_images) == 1:
                        png_path = output_dir / f"translated_{page_no:03d}.png"
                    else:
                        png_path = output_dir / f"translated_{page_no:03d}_{flow_idx+1:02d}.png"
                    canvas.save(str(png_path))
                    images.append(canvas)
            else:
                canvas = self.render_page(page_data, page_no)
                
                png_path = output_dir / f"translated_{page_no:03d}.png"
                canvas.save(str(png_path))
                images.append(canvas)
        
        # Create PDF
        pdf_path = output_dir / "translated.pdf"
        if images:
            images[0].save(
                str(pdf_path), 
                "PDF", 
                resolution=100.0, 
                save_all=True, 
                append_images=images[1:]
            )
        
        for img in images:
            img.close()
        
        # Generate export formats
        try:
            export_service.export_to_docx(doc_result, str(output_dir / "translated.docx"))
            
            # Export to Markdown via delegate
            self._export_to_markdown(doc_result, str(output_dir / "translated.md"))
            
        except Exception as e:
            print(f"⚠️ Export error (non-critical): {e}")
        
        return str(pdf_path)
    
    def _export_to_markdown(self, doc_result: Dict[str, Any], output_path: str):
        """Wrapper for markdown.export_to_markdown"""
        export_to_markdown(doc_result, output_path)


# Singleton instance
render_service = RenderService()
