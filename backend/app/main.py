"""
FastAPI Application Entry Point
Document Translation Web Application
"""
import asyncio
import shutil
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.api import upload, translate, export, logs


# ===== Model Preload =====

async def preload_models():
    """โหลด Ollama model ล่วงหน้า (non-blocking)"""
    import httpx
    
    try:
        print(f"🚀 Preloading model: {settings.TRANSLATION_MODEL}...")
        
        # ส่ง dummy request เพื่อให้ Ollama โหลด model
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.OLLAMA_URL}/api/generate",
                json={
                    "model": settings.TRANSLATION_MODEL,
                    "prompt": "Hello",  # แค่ ping model
                    "stream": False,
                    "options": {"num_predict": 1}  # แค่ 1 token
                }
            )
            
            if response.status_code == 200:
                print(f"✅ Model {settings.TRANSLATION_MODEL} preloaded!")
            else:
                print(f"⚠️ Model preload response: {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                
    except Exception as e:
        print(f"⚠️ Model preload failed (non-critical):")
        print(f"   Error type: {type(e).__name__}")
        print(f"   Error message: {str(e)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    # Startup: Preload model (async, non-blocking)
    asyncio.create_task(preload_models())
    
    yield
    # Shutdown logic (if any)


app = FastAPI(
    title="Document Translation API",
    description="แปลเอกสาร PDF/PNG/JPG พร้อมรักษา layout",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ปรับตาม production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(upload.router, prefix="/api", tags=["Upload"])
app.include_router(translate.router, prefix="/api", tags=["Translation"])
app.include_router(export.router, prefix="/api", tags=["Export"])
app.include_router(logs.router, prefix="/api", tags=["Logs"])

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"

# Mount static directories for CSS and JS
app.mount("/styles", StaticFiles(directory=FRONTEND_DIR / "styles"), name="styles")
app.mount("/scripts", StaticFiles(directory=FRONTEND_DIR / "scripts"), name="scripts")


@app.get("/")
async def serve_frontend():
    """Serve frontend index.html (no cache)"""
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


