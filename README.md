# Document Translation - คู่มือการติดตั้งและใช้งาน

ระบบแปลภาษาจากเอกสาร PDF และเอกสารรูปภาพ

## สิ่งที่ต้องเตรียม (Prerequisites)

สำหรับเครื่องใหม่ที่ยังไม่มีการติดตั้งโปรแกรมใดๆ โปรดติดตั้งสิ่งต่อไปนี้ตามลำดับ:

1.  **Python 3.10 ขึ้นไป**: [ดาวน์โหลด Python](https://www.python.org/downloads/) (แนะนำเวอร์ชัน 3.10 หรือ 3.11 เพื่อความเสถียรของไลบรารี AI)
2.  **Git**: สำหรับการ Clone โปรเจกต์ [ดาวน์โหลด Git](https://git-scm.com/)
3.  **Ollama**: (กรณีต้องการรันโมเดล LLM ในเครื่องตัวเอง) [ดาวน์โหลด Ollama](https://ollama.com/)

---

## ขั้นตอนการติดตั้ง (Installation)

### 1. การเตรียมโปรเจกต์
เปิด Terminal (Command Prompt หรือ PowerShell) และรันคำสั่ง:
```bash
git clone <url-of-this-repository>
cd document-translator
```

### 2. ตั้งค่า Backend (ตัวหลัก)
1. เข้าไปที่โฟลเดอร์ backend:
   ```bash
   cd backend
   ```
2. สร้าง Virtual Environment และ Activate:
   ```bash
   python -m venv venv
   # สำหรับ Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   ```
3. ติดตั้งไลบรารีที่จำเป็น:
   ```bash
   pip install -r requirements.txt
   ```
   **ไลบรารีหลักที่ติดตั้งรวมถึง:**
   - **FastAPI / Uvicorn**: สำหรับสร้างและรัน API Server
   - **PyMuPDF (fitz)**: ใช้สำหรับจัดการไฟล์ PDF (อ่านเนื้อหาและแปลงหน้าเป็นรูปภาพ)
   - **Pillow (PIL)**: ใช้สำหรับประมวลผลรูปภาพ
   - **OpenCV**: สำหรับการจัดการประมวลผลภาพขั้นสูง
   - **CTransformers / SentencePiece**: สำหรับงานด้านภาษาและการแปล (กรณีใช้โมเดลเฉพาะ)
   - **Python-Docx**: สำหรับการส่งออกข้อมูลเป็นไฟล์ .docx

### 3. ตั้งค่า Paddle Service (บริการ OCR)
โปรเจกต์นี้แยก Service สำหรับ OCR ออกมาต่างหาก เพื่อความสะดวกในการจัดการทรัพยากร
1. เข้าไปที่โฟลเดอร์ paddle_service:
   ```bash
   cd paddle_service
   ```
2. สร้าง Virtual Environment และ Activate (แนะนำให้แยกกัน):
   ```bash
   python -m venv venv
   # สำหรับ Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   ```
3. ติดตั้งไลบรารีสำหรับ Paddle:
   ```bash
   pip install -r requirements.txt
   ```
   **ไลบรารีหลักที่ติดตั้งรวมถึง:**
   - **PaddlePaddle**: Engine หลักของ Paddle AI
   - **PaddleOCR**: ตัวจัดการการทำ OCR (ตรวจจับและอ่านข้อความจากภาพ)
   - *หมายเหตุ: หากต้องการใช้งาน GPU สำหรับ OCR โปรดติดตั้ง `paddlepaddle-gpu` แทน `paddlepaddle`*

---

## การตั้งค่า Environment Variables (`.env`)

สร้างไฟล์ที่ชื่อ `.env` ในโฟลเดอร์ `backend/` และใส่ข้อมูลดังนี้:

```env
# Ollama URL (Default คือ http://localhost:11434)
OLLAMA_URL=http://localhost:11434

# Typhoon OCR API Key (กรณีต้องการใช้ OCR ของ Typhoon)
TYPHOON_OCR_API_KEY=your_typhoon_api_key_here
```

---

## วิธีการรันระบบ (Running the System)

คุณต้องเปิด Terminal 2 หน้าต่าง เพื่อรันทั้ง 2 Services พร้อมกัน:

### หน้าต่างที่ 1: รัน Paddle Service (Port 8001)
```bash
cd backend/paddle_service
.\venv\Scripts\Activate.ps1
uvicorn paddle_service:app --host 0.0.0.0 --port 8001 --reload
```

### หน้าต่างที่ 2: รัน Main Backend (Port 8000)
```bash
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## การเข้าใช้งาน Frontend

เนื่องจาก Frontend เป็น static files (HTML/JS/CSS) คุณสามารถเข้าใช้งานได้โดย:
1. การเปิดไฟล์ `frontend/index.html` ด้วยเว็บเบราว์เซอร์ (Chrome, Edge, Firefox) โดยตรง
2. หรือใช้ส่วนเสริมอย่าง **Live Server** ใน VS Code เพื่อเปิดใช้งาน

---

## สรุปโมเดลที่แนะนำให้โหลดสำหรับ Ollama
สำหรับการแปลภาษาและประมวลผล แนะนำให้ติดตั้งโมเดลเหล่านี้:
```bash
ollama pull scb10x/typhoon-translate1.5-4b:latest
ollama pull qwen3:1.7b
```
