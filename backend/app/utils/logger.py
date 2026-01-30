"""
Logging Utility
เก็บ log สำหรับ debug และสถิติ
"""
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from app.config import settings


class JobLogger:
    """Logger สำหรับแต่ละ job"""
    
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.log_dir = settings.OUTPUT_DIR / job_id / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.start_time = datetime.now()
        self.stats = {
            "job_id": job_id,
            "start_time": self.start_time.isoformat(),
            "timings": {},
            "blocks": {}
        }
    
    def log_ocr_start(self):
        """บันทึกเวลาเริ่ม OCR"""
        self.stats["timings"]["ocr_start"] = datetime.now().isoformat()
    
    def log_ocr_complete(self, num_pages: int, total_blocks: int, duration: float):
        """บันทึกผลลัพธ์ OCR"""
        self.stats["timings"]["ocr_end"] = datetime.now().isoformat()
        self.stats["timings"]["ocr_seconds"] = round(duration, 2)
        self.stats["ocr"] = {
            "num_pages": num_pages,
            "total_blocks": total_blocks
        }
    
    def log_translation_start(self):
        """บันทึกเวลาเริ่มแปล"""
        self.stats["timings"]["translation_start"] = datetime.now().isoformat()
    
    def log_translation_complete(self, translated: int, skipped: int, duration: float):
        """บันทึกผลลัพธ์การแปล"""
        self.stats["timings"]["translation_end"] = datetime.now().isoformat()
        self.stats["timings"]["translation_seconds"] = round(duration, 2)
        self.stats["blocks"] = {
            "translated": translated,
            "skipped": skipped,
            "total": translated + skipped
        }
    
    
    def log_render_complete(self, duration: float, output_path: str):
        """บันทึกผลลัพธ์ render"""
        self.stats["timings"]["render_seconds"] = round(duration, 2)
        self.stats["output_path"] = output_path

    def log_languages(self, source_lang: str, target_lang: str):
        """บันทึกภาษาที่ใช้แปล"""
        self.stats["languages"] = {
            "source": source_lang,
            "target": target_lang
        }
    
    def log_ocr_engine(self, ocr_engine: str):
        """บันทึก OCR engine ที่ใช้"""
        self.stats["ocr_engine"] = ocr_engine
    
    def log_translation_mode(self, translation_mode: str):
        """บันทึกโหมดการแปล"""
        self.stats["translation_mode"] = translation_mode

    def log_detected_language(self, detected_lang: str):
        """บันทึกภาษาที่ตรวจพบ (Auto Detect)"""
        self.stats["detected_language"] = detected_lang
    
    def log_block(self, page_no: int, block_idx: int, original: str, translated: str, 
                  detected_lang: str, was_translated: bool, nllb_translated: str = None):
        """บันทึก log ของแต่ละ block (พร้อม NLLB translation ถ้ามี)"""
        # Ensure directory exists (defensive)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = self.log_dir / f"page_{page_no:03d}_blocks.txt"
        
        status = "TRANSLATED" if was_translated else "SKIPPED"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"Block {block_idx} [{status}] (detected: {detected_lang})\n")
            f.write(f"  Original: {original}\n")
            if nllb_translated:  # If NLLB translation exists
                f.write(f"  NLLB:     {nllb_translated}\n")
            f.write(f"  Result:   {translated}\n")
            f.write("-" * 60 + "\n")
    
    def log_table(self, page_no: int, table_idx: int, num_rows: int, num_cols: int, cells: list):
        """บันทึก log ของตาราง"""
        # Ensure directory exists (defensive)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = self.log_dir / f"page_{page_no:03d}_blocks.txt"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"TABLE {table_idx} [{num_rows}x{num_cols}]\n")
            f.write(f"{'='*60}\n")
            
            for cell in cells:
                row = cell.get('row', 0)
                col = cell.get('col', 0)
                original = cell.get('text', '')
                translated = cell.get('translated', original)
                was_translated = cell.get('was_translated', False)
                detected_lang = cell.get('detected_lang', 'unknown')
                status = "TRANSLATED" if was_translated else "SKIPPED"
                
                f.write(f"Cell [{row},{col}] [{status}] (detected: {detected_lang})\n")
                f.write(f"  Original: {original}\n")
                f.write(f"  Result:   {translated}\n")
            
            f.write("-" * 60 + "\n")
    
    def log_error(self, error: str):
        """บันทึก error"""
        self.stats["error"] = error
        self.stats["status"] = "error"
    
    def log_info(self, message: str):
        """บันทึก info message"""
        if "info" not in self.stats:
            self.stats["info"] = []
        self.stats["info"].append({
            "time": datetime.now().isoformat(),
            "message": message
        })
    
    def finalize(self):
        """บันทึกสถิติสุดท้าย"""
        end_time = datetime.now()
        self.stats["end_time"] = end_time.isoformat()
        self.stats["timings"]["total_seconds"] = round(
            (end_time - self.start_time).total_seconds(), 2
        )
        
        if "error" not in self.stats:
            self.stats["status"] = "completed"
        
        # Ensure directory exists (defensive)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # บันทึกไฟล์ stats.json
        stats_file = self.log_dir / "stats.json"
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, ensure_ascii=False, indent=2)
        
        # Print summary
        def format_time(seconds):
            """แปลงวินาทีเป็น m:ss หรือ s"""
            if seconds >= 60:
                mins = int(seconds // 60)
                secs = seconds % 60
                return f"{mins}m {secs:.1f}s"
            return f"{seconds}s"
        
        print(f"\n📊 Job {self.job_id} สรุป:")
        if "languages" in self.stats:
            print(f"   🌐 Lang: {self.stats['languages']['source']} -> {self.stats['languages']['target']}")
        print(f"   ⏱️ OCR: {format_time(self.stats['timings'].get('ocr_seconds', 0))}")
        print(f"   ⏱️ Translation: {format_time(self.stats['timings'].get('translation_seconds', 0))}")
        print(f"   ⏱️ Render: {format_time(self.stats['timings'].get('render_seconds', 0))}")
        print(f"   ⏱️ Total: {format_time(self.stats['timings'].get('total_seconds', 0))}")
        print(f"   📊 Blocks: translated={self.stats['blocks'].get('translated', 0)}, skipped={self.stats['blocks'].get('skipped', 0)}")
        print(f"   📁 Log: {self.log_dir}")
        
        return self.stats


def get_job_logger(job_id: str) -> JobLogger:
    """สร้าง logger สำหรับ job"""
    return JobLogger(job_id)
