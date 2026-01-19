"""
Logs API Endpoint
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import json

from app.config import settings

router = APIRouter()


@router.get("/logs/{job_id}")
async def get_job_logs(job_id: str):
    """
    ดึง log ของ job (stats.json และ block logs)
    """
    log_dir = settings.OUTPUT_DIR / job_id / "logs"
    
    if not log_dir.exists():
        raise HTTPException(status_code=404, detail="Logs not found")
    
    # อ่าน stats.json
    stats_file = log_dir / "stats.json"
    if not stats_file.exists():
        raise HTTPException(status_code=404, detail="Stats file not found")
    
    with open(stats_file, "r", encoding="utf-8") as f:
        stats = json.load(f)
    
    # อ่าน block logs แต่ละหน้า
    block_logs = {}
    for log_file in sorted(log_dir.glob("page_*_blocks.txt")):
        page_num = log_file.stem.split("_")[1]
        with open(log_file, "r", encoding="utf-8") as f:
            block_logs[f"page_{page_num}"] = f.read()
    
    return JSONResponse({
        "job_id": job_id,
        "stats": stats,
        "block_logs": block_logs
    })


@router.get("/logs/{job_id}/stats")
async def get_job_stats(job_id: str):
    """
    ดึงเฉพาะ stats.json
    """
    stats_file = settings.OUTPUT_DIR / job_id / "logs" / "stats.json"
    
    if not stats_file.exists():
        raise HTTPException(status_code=404, detail="Stats file not found")
    
    return FileResponse(
        path=str(stats_file),
        media_type="application/json"
    )
