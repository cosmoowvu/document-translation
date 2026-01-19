"""
Image Utilities
ฟังก์ชันช่วยเหลือสำหรับจัดการรูปภาพ
"""
from PIL import Image
from pathlib import Path


def normalize_image(image_path: str, max_size: int = 2000) -> Image.Image:
    """
    Normalize รูปภาพ - resize ถ้าใหญ่เกินไป
    """
    img = Image.open(image_path)
    
    # Convert to RGB if needed
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Resize if too large
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
    
    return img


def images_to_pdf(image_paths: list, output_path: str, resolution: float = 100.0):
    """
    รวมรูปภาพหลายรูปเป็น PDF
    """
    images = [Image.open(p).convert('RGB') for p in image_paths]
    
    if images:
        images[0].save(
            output_path,
            "PDF",
            resolution=resolution,
            save_all=True,
            append_images=images[1:]
        )
    
    for img in images:
        img.close()
    
    return output_path


def get_image_dimensions(image_path: str) -> tuple:
    """
    ดึงขนาดรูปภาพ (width, height)
    """
    with Image.open(image_path) as img:
        return img.size
