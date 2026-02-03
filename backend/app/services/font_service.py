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
    
    def get_font(self, size: int = 16, text: str = None) -> ImageFont.FreeTypeFont:
        """โหลด font พร้อม caching และ fallback ภาษาต่างๆ (Auto-detect CJK)"""
        
        # Check for specific languages to prioritize fonts
        is_korean = False
        is_japanese = False
        is_cjk_general = False
        
        if text:
            # Hangul Syllables (Korean)
            if any('\uac00' <= char <= '\ud7af' for char in text):
                is_korean = True
                
            # Hiragana/Katakana (Japanese)
            if any('\u3040' <= char <= '\u30ff' for char in text):
                is_japanese = True
                
            # CJK Unified Ideographs (Chinese/Japanese/Korean)
            if any('\u4e00' <= char <= '\u9fff' for char in text):
                is_cjk_general = True

        is_cjk = is_korean or is_japanese or is_cjk_general
        
        # Creates a specialized cache key
        cache_suffix = ""
        if is_korean: cache_suffix = "_kor"
        elif is_japanese: cache_suffix = "_jpn"
        elif is_cjk_general: cache_suffix = "_cjk"
        
        cache_key = f"{size}{cache_suffix}"
        
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]
        
        fonts_to_try = []
        
        # Define font groups
        fonts_korean = [
            "C:/Windows/Fonts/malgun.ttf",       # Malgun Gothic
            "C:/Windows/Fonts/gulim.ttc",        # Gulim
            "C:/Windows/Fonts/batang.ttc",       # Batang
        ]
        
        fonts_japanese = [
            "C:/Windows/Fonts/msgothic.ttc",     # MS Gothic
            "C:/Windows/Fonts/meiryo.ttc",       # Meiryo
        ]
        
        fonts_chinese = [
            "C:/Windows/Fonts/msyh.ttc",         # Microsoft YaHei
            "C:/Windows/Fonts/simsun.ttc",       # SimSun
            "C:/Windows/Fonts/simhei.ttf",       # SimHei
        ]
        
        fonts_universal = [
            "C:/Windows/Fonts/arialuni.ttf",     # Arial Unicode MS
            "C:/Windows/Fonts/micross.ttf",      # Microsoft Sans Serif
        ]
        
        thai_fonts = [
            self.font_path,                      # Configured Font (Primary)
            "C:/Windows/Fonts/LeelawadeeUI.ttf", 
            "C:/Windows/Fonts/tahoma.ttf",       
        ]
        
        # Build priority list based on detected language
        if is_korean:
            # Korean > Universal > Chinese/Japanese (as fallback) > Thai
            fonts_to_try = fonts_korean + fonts_universal + fonts_chinese + fonts_japanese + thai_fonts
            print(f"DEBUG: Korean text detected, prioritization: {fonts_to_try[0]}...")
            
        elif is_japanese:
            # Japanese > Universal > Chinese > Korean > Thai
            fonts_to_try = fonts_japanese + fonts_universal + fonts_chinese + fonts_korean + thai_fonts
            print(f"DEBUG: Japanese text detected, prioritization: {fonts_to_try[0]}...")
            
        elif is_cjk_general:
            # Chinese (Default CJK) > Universal > Japanese > Korean > Thai
            fonts_to_try = fonts_chinese + fonts_universal + fonts_japanese + fonts_korean + thai_fonts
            print(f"DEBUG: Generic CJK detected, prioritization: {fonts_to_try[0]}...")
            
        else:
            # Standard Thai/English -> CJK fallbacks just in case
            fonts_to_try = thai_fonts + fonts_universal + fonts_chinese
            
        # Add fallback universal
        fonts_to_try.append("C:/Windows/Fonts/seguiemj.ttf")

        for font_path in fonts_to_try:
            if font_path and os.path.exists(font_path):
                try:
                    # Try loading standard
                    font = ImageFont.truetype(font_path, size)
                    self._font_cache[cache_key] = font
                    # print(f"   ✅ LOADED FONT: {font_path}")
                    return font
                except Exception as e:
                    # Retry with index=0 for TTC files if failed
                    if font_path.lower().endswith(".ttc"):
                        try:
                            font = ImageFont.truetype(font_path, size, index=0)
                            self._font_cache[cache_key] = font
                            print(f"   ✅ LOADED FONT (Index 0): {font_path}")
                            return font
                        except:
                            pass
                    
                    print(f"   ⚠️ FAILED to load {font_path}: {e}")
                    continue
        
        # Final fallback
        print("   ⚠️ No custom/system font found, using default")
        return ImageFont.load_default()
    
    def wrap_text(self, text: str, font, max_width: int, draw) -> List[str]:
        """ตัดคำให้พอดี width - รองรับภาษาไทย (PyThaiNLP) และภาษาอื่นๆ"""
        try:
            # Check for CJK characters (Japanese, Chinese, Korean)
            # These languages generally don't use spaces, so we wrap by character
            is_cjk = any('\u4e00' <= char <= '\u9fff' or '\u3040' <= char <= '\u30ff' or '\uac00' <= char <= '\ud7af' for char in text)
            
            if is_cjk:
                # Tokenize by character for CJK
                words = list(text)
            else:
                from pythainlp.tokenize import word_tokenize
                from pythainlp.util import normalize as normalize_thai
                
                # Normalize Thai text (Fix vowel sequence order)
                if any('\u0E00' <= char <= '\u0E7F' for char in text):
                    text = normalize_thai(text)

                # ใช้ engine 'newmm' (dictionary-based) ซึ่งเร็วและแม่นยำพอสมควร
                words = word_tokenize(text, engine="newmm", keep_whitespace=True)
                
        except ImportError:
            # Fallback (rarely happens if requirements installed)
            # If CJK (checked manually here again if needed, but handled above), convert to chars
            if any('\u4e00' <= char <= '\u9fff' or '\u3040' <= char <= '\u30ff' for char in text):
                 words = list(text)
            else:
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
            # Pass text to detect language specific font requirements
            font = self.get_font(size, text=text) 
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
        font = self.get_font(min_font, text=text)
        wrapped = self.wrap_text(text, font, bbox_width, draw)
        
        return font, wrapped


# Singleton instance
font_service = FontService()
