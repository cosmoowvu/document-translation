"""
Cache Service
Result caching based on file hash + translation parameters
"""
import hashlib
import shutil
import json
from pathlib import Path
from typing import Optional, Tuple

from app.config import settings


# Cache index file
CACHE_INDEX_FILE = settings.OUTPUT_DIR / ".cache_index.json"


def compute_file_hash(file_path: str) -> str:
    """คำนวณ MD5 hash ของไฟล์"""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        # Read in chunks for large files
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_cache_key(file_hash: str, source_lang: str, target_lang: str, model: str, ocr_engine: str = "docling") -> str:
    """สร้าง cache key จาก hash + parameters (รวม OCR engine ด้วย)"""
    return f"{file_hash}_{source_lang}_{target_lang}_{model}_{ocr_engine}"


def load_cache_index() -> dict:
    """โหลด cache index จากไฟล์"""
    if CACHE_INDEX_FILE.exists():
        try:
            with open(CACHE_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cache_index(index: dict):
    """บันทึก cache index"""
    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def check_cache(cache_key: str) -> Optional[str]:
    """
    ตรวจสอบว่ามี cached result หรือไม่
    Returns: cached_job_id หรือ None
    """
    index = load_cache_index()
    
    if cache_key in index:
        cached_job_id = index[cache_key]
        # ตรวจว่า output ยังอยู่จริง
        cached_output = settings.OUTPUT_DIR / cached_job_id
        if cached_output.exists():
            return cached_job_id
        else:
            # Cache entry แต่ไฟล์หายไปแล้ว - ลบ entry
            del index[cache_key]
            save_cache_index(index)
    
    return None


def save_to_cache(cache_key: str, job_id: str):
    """บันทึก job_id ลง cache"""
    index = load_cache_index()
    index[cache_key] = job_id
    save_cache_index(index)
    print(f"💾 Cached: {cache_key[:16]}... → {job_id[:8]}...")


def copy_cached_result(cached_job_id: str, new_job_id: str) -> Tuple[bool, str]:
    """
    Copy ผลลัพธ์จาก cached job ไปยัง new job
    Returns: (success, output_path)
    """
    try:
        cached_output = settings.OUTPUT_DIR / cached_job_id
        new_output = settings.OUTPUT_DIR / new_job_id
        
        if not cached_output.exists():
            return False, ""
        
        # Copy entire output directory
        shutil.copytree(cached_output, new_output, dirs_exist_ok=True)
        
        # Find main output file (PDF or images)
        pdf_files = list(new_output.glob("translated*.pdf"))
        if pdf_files:
            return True, str(pdf_files[0])
        
        png_files = list(new_output.glob("page_*.png"))
        if png_files:
            return True, str(new_output)
        
        return True, str(new_output)
        
    except Exception as e:
        print(f"⚠️ Cache copy error: {e}")
        return False, ""


def clear_cache():
    """ลบ cache index ทั้งหมด"""
    if CACHE_INDEX_FILE.exists():
        CACHE_INDEX_FILE.unlink()
    print("🗑️ Cache cleared")
