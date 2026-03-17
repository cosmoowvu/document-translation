"""
Upload API Endpoint
"""
import uuid
import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.config import settings
from app.services.cache_service import compute_file_hash, clear_cache

router = APIRouter()


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    อัปโหลดไฟล์ PDF/PNG/JPG
    Returns: job_id สำหรับติดตามสถานะ + file_hash สำหรับ caching
    """
    # ตรวจสอบ extension
    ext = file.filename.split(".")[-1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"ไม่รองรับไฟล์ .{ext} (รองรับ: {settings.ALLOWED_EXTENSIONS})"
        )
    
    # ตรวจสอบขนาด
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"ไฟล์ใหญ่เกิน {settings.MAX_FILE_SIZE // (1024*1024)}MB"
        )
    
    # สร้าง job_id
    job_id = str(uuid.uuid4())
    
    # สร้างโฟลเดอร์สำหรับ job
    job_dir = settings.UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # บันทึกไฟล์
    file_path = job_dir / f"original.{ext}"
    with open(file_path, "wb") as f:
        f.write(content)
    
    # คำนวณ file hash สำหรับ caching
    file_hash = compute_file_hash(str(file_path))
    
    return {
        "job_id": job_id,
        "filename": file.filename,
        "file_type": ext,
        "file_size": len(content),
        "file_hash": file_hash,  # เพิ่ม hash สำหรับ Result Caching
        "status": "uploaded"
    }


@router.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """
    ลบไฟล์ทั้งหมดของ job (uploads และ outputs)
    """
    deleted = {"uploads": False, "outputs": False}
    errors = []
    
    try:
        # ลบ upload directory
        upload_dir = settings.UPLOAD_DIR / job_id
        if upload_dir.exists():
            shutil.rmtree(upload_dir)
            deleted["uploads"] = True
    except Exception as e:
        errors.append(f"Upload dir error: {str(e)}")
    
    try:
        # ลบ output directory
        output_dir = settings.OUTPUT_DIR / job_id
        if output_dir.exists():
            shutil.rmtree(output_dir)
            deleted["outputs"] = True
    except Exception as e:
        errors.append(f"Output dir error: {str(e)}")
    
    return {
        "job_id": job_id,
        "status": "deleted" if (deleted["uploads"] or deleted["outputs"]) else "not_found",
        "deleted": deleted,
        "errors": errors if errors else None
    }


@router.post("/cleanup")
async def cleanup_all():
    """
    ลบไฟล์ทั้งหมดใน uploads และ outputs (สำหรับ cleanup)
    """
    deleted_count = {"uploads": 0, "outputs": 0, "cache": 0}
    errors = []
    
    try:
        # ลบทุกโฟลเดอร์ใน uploads
        if settings.UPLOAD_DIR.exists():
            for item in settings.UPLOAD_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                    deleted_count["uploads"] += 1
    except Exception as e:
        errors.append(f"Upload cleanup error: {str(e)}")
    
    try:
        # ลบทุกโฟลเดอร์ใน outputs
        if settings.OUTPUT_DIR.exists():
            for item in settings.OUTPUT_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                    deleted_count["outputs"] += 1
                    
        # ✅ Clear cache index as well
        clear_cache()
        deleted_count["cache"] = 1
        print("🗑️ Cleared cache index")
        
    except Exception as e:
        errors.append(f"Output cleanup error: {str(e)}")
    
    return {
        "status": "cleaned",
        "deleted_count": deleted_count,
        "errors": errors if errors else None
    }
