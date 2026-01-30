"""
Translation API Endpoint
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from app.config import settings
from app.services.translation_service import process_translation
from app.services.cache_service import (
    compute_file_hash, get_cache_key, check_cache, 
    save_to_cache, copy_cached_result
)

router = APIRouter()


class TranslateRequest(BaseModel):
    job_id: str
    source_lang: str = "tha_Thai"
    target_lang: str = "eng_Latn"
    translation_mode: str = "qwen_direct"  # qwen_direct, gemma_direct, google_qwen, google_gemma
    ocr_engine: str = "docling"  # ✅ Add OCR engine selection


class TranslateResponse(BaseModel):
    job_id: str
    status: str
    message: str
    cached: bool = False  # บอกว่าใช้ cache หรือไม่


# In-memory job status (ใช้ Redis ใน production)
job_status = {}


@router.post("/translate", response_model=TranslateResponse)
async def translate_document(
    request: TranslateRequest,
    background_tasks: BackgroundTasks
):
    """
    เริ่มกระบวนการแปลเอกสาร (Background task)
    ถ้ามี cached result จะใช้ผลเก่าแทน
    """
    job_id = request.job_id
    job_dir = settings.UPLOAD_DIR / job_id
    
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    
    # ตรวจสอบว่ามีไฟล์ original
    original_files = list(job_dir.glob("original.*"))
    if not original_files:
        raise HTTPException(status_code=404, detail="Original file not found")
    
    # ✅ ตรวจสอบภาษาต้นฉบับ vs ภาษาเป้าหมาย
    if request.source_lang == request.target_lang:
        raise HTTPException(
            status_code=400, 
            detail="ภาษาต้นฉบับเหมือนกับภาษาที่ต้องการแปล กรุณาเลือกภาษาอื่น"
        )
    
    # ===== Result Caching =====
    file_path = str(original_files[0])
    file_hash = compute_file_hash(file_path)
    translation_mode = request.translation_mode or "qwen_direct"
    ocr_engine = request.ocr_engine or "docling"
    cache_key = get_cache_key(file_hash, request.source_lang, request.target_lang, translation_mode, ocr_engine)
    
    # ตรวจ cache
    cached_job_id = check_cache(cache_key)
    if cached_job_id:
        print(f"🎯 Cache HIT: {cache_key[:16]}... → {cached_job_id[:8]}...")
        
        # Copy cached result to new job
        success, output_path = copy_cached_result(cached_job_id, job_id)
        
        if success:
            # ✅ Load stats from cached job
            stats = {}
            cached_stats_file = settings.OUTPUT_DIR / cached_job_id / "logs" / "stats.json"
            if cached_stats_file.exists():
                try:
                    import json
                    with open(cached_stats_file, "r", encoding="utf-8") as f:
                        raw_stats = json.load(f)
                    # Format stats to match frontend expectations
                    stats = {
                        "ocr_seconds": raw_stats.get("timings", {}).get("ocr_seconds", 0),
                        "translate_seconds": raw_stats.get("timings", {}).get("translation_seconds", 0),
                        "render_seconds": raw_stats.get("timings", {}).get("render_seconds", 0),
                        "total_seconds": raw_stats.get("timings", {}).get("total_seconds", 0),
                        "blocks_translated": raw_stats.get("blocks", {}).get("translated", 0),
                        "blocks_skipped": raw_stats.get("blocks", {}).get("skipped", 0),
                        "languages": raw_stats.get("languages", {}),
                        "ocr_engine": raw_stats.get("ocr_engine", "docling"),
                        "translation_mode": raw_stats.get("translation_mode", "qwen_direct"),
                        "detected_language": raw_stats.get("detected_language") # ✅ Add detected language
                    }
                    print(f"   📊 Loaded stats from cache: OCR={stats.get('ocr_engine')}, Time={stats.get('total_seconds')}s")
                except Exception as e:
                    print(f"   ⚠️ Error loading cached stats: {e}")
            
            job_status[job_id] = {
                "status": "completed",
                "progress": 100,
                "message": "ใช้ผลลัพธ์ที่เคยแปลไว้ (cached)",
                "output_path": output_path,
                "cached": True,
                "stats": stats  # ✅ Include stats
            }
            
            return TranslateResponse(
                job_id=job_id,
                status="completed",
                message="ใช้ผลลัพธ์ที่เคยแปลไว้ (cached)",
                cached=True
            )
    
    print(f"🔄 Cache MISS: {cache_key[:16]}... → processing")
    
    # ===== Normal Translation =====
    # สร้าง job status ใหม่
    job_status[job_id] = {
        "status": "processing",
        "progress": 5,
        "message": "กำลังเตรียมการ...",
        "cancelled": False  # เพิ่ม flag
    }
    
    # เริ่ม background task (เพิ่ม cache_key สำหรับ save หลังเสร็จ)
    background_tasks.add_task(
        process_translation,
        job_id=job_id,
        file_path=file_path,
        source_lang=request.source_lang,
        target_lang=request.target_lang,
        job_status=job_status,
        translation_mode=request.translation_mode,
        cache_key=cache_key,  # ส่ง cache_key ไปด้วย
        ocr_engine=request.ocr_engine  # ✅ Pass OCR engine
    )
    
    return TranslateResponse(
        job_id=job_id,
        status="processing",
        message="เริ่มกระบวนการแปลแล้ว",
        cached=False
    )


@router.get("/status/{job_id}")
async def get_status(job_id: str):
    """
    ตรวจสอบสถานะการแปล
    ถ้า server restart แล้ว job_status หายไป จะตรวจจาก output folder แทน
    """
    if job_id in job_status:
        return {"job_id": job_id, **job_status[job_id]}
    
    # Fallback: ตรวจสอบว่ามี output อยู่แล้วหรือไม่ (กรณี server restart)
    output_dir = settings.OUTPUT_DIR / job_id
    if output_dir.exists():
        # ตรวจว่ามีผลลัพธ์หรือไม่
        pdf_files = list(output_dir.glob("translated*.pdf"))
        png_files = list(output_dir.glob("page_*.png"))
        
        if pdf_files or png_files:
            # มี output แล้ว = เสร็จแล้ว!
            output_path = str(pdf_files[0]) if pdf_files else str(output_dir)
            
            # Try to load stats
            stats = {}
            stats_file = output_dir / "logs" / "stats.json"
            if stats_file.exists():
                try:
                    import json
                    with open(stats_file, "r", encoding="utf-8") as f:
                        raw_stats = json.load(f)
                    # Format stats to match frontend expectations
                    stats = {
                        "ocr_seconds": raw_stats.get("timings", {}).get("ocr_seconds", 0),
                        "translate_seconds": raw_stats.get("timings", {}).get("translation_seconds", 0),
                        "render_seconds": raw_stats.get("timings", {}).get("render_seconds", 0),
                        "total_seconds": raw_stats.get("timings", {}).get("total_seconds", 0),
                        "blocks_translated": raw_stats.get("blocks", {}).get("translated", 0),
                        "blocks_skipped": raw_stats.get("blocks", {}).get("skipped", 0),
                        "languages": raw_stats.get("languages", {}),
                        "ocr_engine": raw_stats.get("ocr_engine", "docling"),  # ✅ Add OCR engine
                        "translation_mode": raw_stats.get("translation_mode", "qwen_direct"),  # ✅ Add translation mode
                        "detected_language": raw_stats.get("detected_language") # ✅ Add detected language
                    }
                except Exception as e:
                    print(f"Error loading stats: {e}")

            return {
                "job_id": job_id,
                "status": "completed",
                "progress": 100,
                "message": "เสร็จสิ้น (recovered from output folder)",
                "output_path": output_path,
                "stats": stats
            }
    
    # ตรวจสอบว่า job มีอยู่จริง
    job_dir = settings.UPLOAD_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    
    # ✅ ถ้ามีไฟล์แต่ไม่มีใน memory และไม่มี output = งานหลุดไประหว่าง server restart
    return {
        "job_id": job_id, 
        "status": "error", 
        "progress": 0,
        "message": "กระบวนการถูกขัดจังหวะ (Server Restart) กรุณาเริ่มใหม่"
    }


@router.delete("/cancel/{job_id}")
async def cancel_job(job_id: str):
    """
    ยกเลิกกระบวนการแปล
    """
    if job_id not in job_status:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Set cancelled flag
    job_status[job_id]["cancelled"] = True
    job_status[job_id]["status"] = "cancelled"
    job_status[job_id]["message"] = "ยกเลิกกระบวนการแล้ว"
    
    print(f"🚫 Job {job_id[:8]}... cancelled by user")
    
    return {
        "job_id": job_id,
        "status": "cancelled",
        "message": "ยกเลิกกระบวนการเรียบร้อยแล้ว"
    }
