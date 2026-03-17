"""
Application Configuration
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    OUTPUT_DIR: Path = BASE_DIR / "outputs"
    
    # OCR Settings
    DPI: int = 200
    
    # Ollama / Translation
    OLLAMA_URL: str = "http://localhost:11434"
    TRANSLATION_MODEL: str = "scb10x/typhoon-translate1.5-4b:latest"  # Typhoon Translation 1.5 (4B)
    FALLBACK_MODEL: str = "qwen3:1.7b" # สำรองเมื่อ Typhoon ล้มเหลว
    BATCH_SIZE: int = 3  # จำนวน blocks ต่อ batch (ลดลงเพื่อให้ Qwen แม่นขึ้น)
    PRELOAD_MODELS: bool = True  # Set to True to preload model on startup
    
    
    # Font
    FONT_PATH: str = "C:/Windows/Fonts/tahoma.ttf"
    
    # Limits
    MAX_FILE_SIZE: int = 30 * 1024 * 1024  # 30MB
    ALLOWED_EXTENSIONS: list = ["pdf", "png", "jpg", "jpeg", "docx", "pptx", "xlsx", "html"]
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # ไม่สนใจ fields อื่นใน .env ที่ไม่ได้กำหนดไว้


settings = Settings()

# Create directories
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
