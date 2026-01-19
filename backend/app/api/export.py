"""
Export API Endpoint
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import zipfile
import io
import shutil

from app.config import settings

router = APIRouter()


@router.get("/export/{job_id}")
async def export_file(job_id: str, format: str = "pdf"):
    """
    ดาวน์โหลดไฟล์ที่แปลแล้ว
    format: pdf, png, jpg, docx
    """
    output_dir = settings.OUTPUT_DIR / job_id
    
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Output not found")
    
    # หาไฟล์ตาม format
    if format == "pdf":
        file_path = output_dir / "translated.pdf"
        media_type = "application/pdf"
    elif format in ["png", "jpg", "jpeg"]:
        # หารูปที่แปลแล้ว
        files = sorted(list(output_dir.glob("translated_*.png")))
        if not files:
            raise HTTPException(status_code=404, detail=f"No image files found")
        
        # ถ้ามีแค่ 1 รูป (ไฟล์ต้นฉบับเป็นรูปภาพ) → ส่งไฟล์เดี่ยวๆ
        if len(files) == 1:
            img_file = files[0]
            
            if format in ["jpg", "jpeg"]:
                # แปลง PNG เป็น JPG
                from PIL import Image
                jpg_path = output_dir / "translated_001.jpg"
                if not jpg_path.exists():
                    img = Image.open(img_file)
                    rgb_img = img.convert('RGB')
                    rgb_img.save(jpg_path, 'JPEG', quality=95)
                    rgb_img.close()
                    img.close()
                return FileResponse(
                    path=str(jpg_path),
                    media_type="image/jpeg",
                    filename=f"translated.jpg"
                )
            else:
                return FileResponse(
                    path=str(img_file),
                    media_type="image/png",
                    filename=f"translated.png"
                )
        
        # ถ้ามีหลายรูป (ไฟล์ต้นฉบับเป็น PDF) → สร้าง ZIP
        zip_path = output_dir / f"translated_images.zip"
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, img_file in enumerate(files, 1):
                # ถ้าต้องการ JPG ต้องแปลงก่อน
                if format in ["jpg", "jpeg"]:
                    from PIL import Image
                    jpg_path = output_dir / f"translated_{i:03d}.jpg"
                    if not jpg_path.exists():
                        img = Image.open(img_file)
                        rgb_img = img.convert('RGB')
                        rgb_img.save(jpg_path, 'JPEG', quality=95)
                        rgb_img.close()
                        img.close()
                    zipf.write(jpg_path, f"translated_{i:03d}.jpg")
                else:
                    zipf.write(img_file, img_file.name)
        
        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=f"translated_images_{job_id}.zip"
        )
    elif format == "docx":
        file_path = output_dir / "translated.docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif format == "pptx":
        file_path = output_dir / "translated.pptx"
        media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    elif format == "xlsx":
        file_path = output_dir / "translated.xlsx"
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif format == "html":
        file_path = output_dir / "translated.html"
        media_type = "text/html"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not ready")
    
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name
    )


@router.get("/preview/{job_id}")
async def preview_file(job_id: str, page: int = 1):
    """
    ดู preview รูปภาพหน้าที่ต้องการ
    """
    output_dir = settings.OUTPUT_DIR / job_id
    
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Output not found")
    
    # หารูปหน้าที่ต้องการ
    file_path = output_dir / f"translated_{page:03d}.png"
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Page {page} not found")
    
    return FileResponse(
        path=str(file_path),
        media_type="image/png"
    )


@router.get("/preview/{job_id}/original")
async def preview_original_file(job_id: str, page: int = 1):
    """
    ดู preview ไฟล์ต้นฉบับหน้าที่ต้องการ
    """
    output_dir = settings.OUTPUT_DIR / job_id
    
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Output not found")
    
    # หารูปหน้าที่ต้องการ
    file_path = output_dir / f"original_{page:03d}.png"
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Original page {page} not found")
    
    return FileResponse(
        path=str(file_path),
        media_type="image/png"
    )


@router.get("/original/{job_id}")
async def get_original_file(job_id: str, as_image: bool = False):
    """
    ดึงไฟล์ต้นฉบับที่อัปโหลด
    as_image=True จะแปลงเป็น PNG สำหรับแสดงผล
    """
    upload_dir = settings.UPLOAD_DIR / job_id
    
    if not upload_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    
    # หาไฟล์ original
    original_files = list(upload_dir.glob("original.*"))
    if not original_files:
        raise HTTPException(status_code=404, detail="Original file not found")
    
    file_path = original_files[0]
    ext = file_path.suffix.lower()
    
    # ถ้าต้องการ image preview และเป็น PDF
    if as_image and ext == ".pdf":
        # แปลง PDF เป็น PNG
        try:
            from pdf2image import convert_from_path
            
            # แปลงหน้าแรกเป็น PNG
            output_dir = settings.OUTPUT_DIR / job_id
            output_dir.mkdir(parents=True, exist_ok=True)
            
            preview_path = output_dir / "original_preview.png"
            
            # ถ้ามีแล้วก็ส่งเลย
            if preview_path.exists():
                return FileResponse(
                    path=str(preview_path),
                    media_type="image/png"
                )
            
            # แปลงหน้าแรก
            images = convert_from_path(
                str(file_path),
                first_page=1,
                last_page=1,
                dpi=150
            )
            
            if images:
                images[0].save(str(preview_path), 'PNG')
                images[0].close()
                
                return FileResponse(
                    path=str(preview_path),
                    media_type="image/png"
                )
        except Exception as e:
            print(f"⚠️ PDF conversion error: {e}")
            # ถ้าแปลงไม่ได้ ส่ง PDF ไปเลย
    
    # กำหนด media type
    media_types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg"
    }
    media_type = media_types.get(ext, "application/octet-stream")
    
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=f"original{ext}"
    )

