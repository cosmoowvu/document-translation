"""
Font Service
จัดการ Font Loading, Text Wrapping, และ Text Fitting สำหรับ Rendering
"""
import os
import re
from typing import List, Tuple
from PIL import ImageFont

from app.config import settings


class FontService:
    def __init__(self):
        self.font_path = settings.FONT_PATH
        self._font_cache = {}
    
    def get_font(self, size: int = 16) -> ImageFont.FreeTypeFont:
        """โหลด font พร้อม caching"""
        if size in self._font_cache:
            return self._font_cache[size]
        
        if os.path.exists(self.font_path):
            try:
                font = ImageFont.truetype(self.font_path, size)
                self._font_cache[size] = font
                return font
            except:
                pass
        return ImageFont.load_default()
    
    def wrap_text(self, text: str, font, max_width: int, draw) -> List[str]:
        """ตัดคำให้พอดี width - รองรับภาษาไทย (PyThaiNLP) และภาษาอื่นๆ"""
        try:
            from pythainlp.tokenize import word_tokenize
            from pythainlp.util import normalize as normalize_thai
            
            # Normalize Thai text (Fix vowel sequence order)
            if any('\u0E00' <= char <= '\u0E7F' for char in text):
                text = normalize_thai(text)

            # ใช้ engine 'newmm' (dictionary-based) ซึ่งเร็วและแม่นยำพอสมควร
            words = word_tokenize(text, engine="newmm", keep_whitespace=True)
        except ImportError:
            print("⚠️ PyThaiNLP not found, falling back to simple split")
            words = re.findall(r'\S+|\s+', text)

        lines = []
        current_line = ""
        
        for word in words:
            # ลองต่อคำเข้ากับบรรทัดเดิม
            test_line = current_line + word
            bbox = draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]
            
            if width <= max_width:
                current_line = test_line
            else:
                # ถ้าบรรทัดเดิมไม่ว่าง ให้ตัดลงบรรทัดใหม่
                if current_line:
                    lines.append(current_line)
                    current_line = word
                else:
                    # กรณีคำเดียวยาวกว่าบรรทัด (เช่น URL) ต้องตัดตัวอักษร
                    lines.append(word)
                    current_line = ""
        
        if current_line:
            lines.append(current_line)
        
        return lines if lines else [text]
    
    def fit_text_to_bbox(self, draw, text: str, bbox_width: int, bbox_height: int,
                         max_font: int = 36, min_font: int = 12) -> Tuple[ImageFont.FreeTypeFont, List[str]]:
        """คำนวณ font size และ wrap text ให้พอดี bbox"""
        # ลด max font สำหรับข้อความยาว
        text_length = len(text)
        if text_length > 200:
            max_font = min(max_font, 24)
        elif text_length > 100:
            max_font = min(max_font, 28)
        
        for size in range(max_font, min_font - 1, -1):
            font = self.get_font(size)
            wrapped = self.wrap_text(text, font, bbox_width, draw)
            
            # คำนวณความสูงรวม (Dynamic line spacing)
            line_spacing = int(size * 0.2)
            total_height = 0
            for i, line in enumerate(wrapped):
                line_bbox = draw.textbbox((0, 0), line, font=font)
                h = line_bbox[3] - line_bbox[1]
                total_height += h
                if i < len(wrapped) - 1:
                    total_height += line_spacing
            
            if total_height <= bbox_height:
                return font, wrapped
        
        # ใช้ min font และ warn ถ้า overflow
        font = self.get_font(min_font)
        wrapped = self.wrap_text(text, font, bbox_width, draw)
        
        return font, wrapped


# Singleton instance
font_service = FontService()
