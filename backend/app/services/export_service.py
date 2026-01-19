"""
Export Service
สร้างไฟล์ output หลายรูปแบบ: DOCX, PPTX, XLSX, HTML
"""
import os
from typing import Dict, Any, List
from pathlib import Path

from app.config import settings


class ExportService:
    """Service for exporting translated documents to various formats"""
    
    def export_to_docx(self, doc_result: Dict[str, Any], output_path: str) -> str:
        """
        Export to Word document
        แต่ละ page = 1 section, blocks = paragraphs
        """
        from docx import Document
        from docx.shared import Pt, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        
        doc = Document()
        
        for page_no in range(1, doc_result["num_pages"] + 1):
            page_data = doc_result["pages"][page_no]
            
            # เพิ่ม page header
            if page_no > 1:
                doc.add_page_break()
            
            # เพิ่ม blocks เป็น paragraphs
            for block in page_data["blocks"]:
                text = block.get("text", "")
                label = block.get("label", "text")
                
                if not text.strip():
                    continue
                
                para = doc.add_paragraph()
                run = para.add_run(text)
                
                # Style based on label
                if "header" in label.lower() or "title" in label.lower():
                    run.bold = True
                    run.font.size = Pt(14)
                elif "list" in label.lower():
                    para.style = "List Bullet"
                else:
                    run.font.size = Pt(11)
        
        doc.save(output_path)
        return output_path
    
    def export_to_pptx(self, doc_result: Dict[str, Any], output_path: str) -> str:
        """
        Export to PowerPoint
        แต่ละ page = 1 slide
        """
        from pptx import Presentation
        from pptx.util import Inches, Pt
        
        prs = Presentation()
        prs.slide_width = Inches(10)
        prs.slide_height = Inches(7.5)
        
        blank_layout = prs.slide_layouts[6]  # Blank layout
        
        for page_no in range(1, doc_result["num_pages"] + 1):
            page_data = doc_result["pages"][page_no]
            slide = prs.slides.add_slide(blank_layout)
            
            # รวม text ทั้งหมดใน page
            all_text = []
            for block in page_data["blocks"]:
                text = block.get("text", "")
                if text.strip():
                    all_text.append(text)
            
            if all_text:
                # สร้าง text box
                textbox = slide.shapes.add_textbox(
                    Inches(0.5), Inches(0.5),
                    Inches(9), Inches(6.5)
                )
                tf = textbox.text_frame
                tf.word_wrap = True
                
                # เพิ่มข้อความ
                for i, text in enumerate(all_text):
                    if i == 0:
                        tf.paragraphs[0].text = text
                    else:
                        p = tf.add_paragraph()
                        p.text = text
                    
                    # set font size
                    for run in tf.paragraphs[-1].runs:
                        run.font.size = Pt(12)
        
        prs.save(output_path)
        return output_path
    
    def export_to_xlsx(self, doc_result: Dict[str, Any], output_path: str) -> str:
        """
        Export to Excel
        columns: Page, Block#, Label, Text
        """
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Translated Text"
        
        # Headers
        headers = ["Page", "Block#", "Label", "Text"]
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
        
        # Data rows
        row_num = 2
        for page_no in range(1, doc_result["num_pages"] + 1):
            page_data = doc_result["pages"][page_no]
            
            for block_idx, block in enumerate(page_data["blocks"], 1):
                text = block.get("text", "")
                label = block.get("label", "text")
                
                ws.cell(row=row_num, column=1, value=page_no)
                ws.cell(row=row_num, column=2, value=block_idx)
                ws.cell(row=row_num, column=3, value=label)
                cell = ws.cell(row=row_num, column=4, value=text)
                cell.alignment = Alignment(wrap_text=True)
                
                row_num += 1
        
        # Adjust column widths
        ws.column_dimensions['A'].width = 8
        ws.column_dimensions['B'].width = 10
        ws.column_dimensions['C'].width = 15
        ws.column_dimensions['D'].width = 80
        
        wb.save(output_path)
        return output_path
    
    def export_to_html(self, doc_result: Dict[str, Any], output_path: str) -> str:
        """
        Export to HTML
        """
        html_parts = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "    <meta charset='UTF-8'>",
            "    <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
            "    <title>Translated Document</title>",
            "    <style>",
            "        body { font-family: 'Segoe UI', Tahoma, Geneva, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }",
            "        .page { border-bottom: 2px solid #ccc; margin-bottom: 30px; padding-bottom: 20px; }",
            "        .page-header { color: #666; font-size: 12px; margin-bottom: 10px; }",
            "        .block { margin-bottom: 10px; }",
            "        .header { font-weight: bold; font-size: 1.2em; color: #333; }",
            "        .list-item { margin-left: 20px; }",
            "        .list-item::before { content: '• '; }",
            "    </style>",
            "</head>",
            "<body>",
        ]
        
        for page_no in range(1, doc_result["num_pages"] + 1):
            page_data = doc_result["pages"][page_no]
            
            html_parts.append(f"    <div class='page'>")
            html_parts.append(f"        <div class='page-header'>Page {page_no}</div>")
            
            for block in page_data["blocks"]:
                text = block.get("text", "")
                label = block.get("label", "text")
                
                if not text.strip():
                    continue
                
                # Escape HTML
                text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                
                # Apply class based on label
                css_class = "block"
                if "header" in label.lower() or "title" in label.lower():
                    css_class = "block header"
                elif "list" in label.lower():
                    css_class = "block list-item"
                
                html_parts.append(f"        <div class='{css_class}'>{text}</div>")
            
            html_parts.append("    </div>")
        
        html_parts.extend([
            "</body>",
            "</html>"
        ])
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(html_parts))
        
        return output_path


# Singleton instance
export_service = ExportService()
