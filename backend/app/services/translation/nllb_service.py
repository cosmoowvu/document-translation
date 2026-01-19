"""
NLLB Translation Service
Handles translation using NLLB-200-600M model with CTranslate2
"""
import os
from typing import List, Optional
from pathlib import Path


class NLLBTranslator:
    """
    NLLB translation service with explicit model loading/unloading
    to optimize VRAM usage
    """
    def __init__(self, model_path: str = "models/nllb-200-1.3B-ct2"):
        self.model_path = Path(model_path)
        self.translator = None
        self.sp_model = None
        self._is_loaded = False
    
    def _map_lang_code(self, lang_code: str) -> str:
        """Map internal language codes to NLLB codes"""
        # NLLB-200 uses these exact language codes
        mapping = {
            "tha_Thai": "tha_Thai",  # Thai (no tha_Latn in NLLB!)
            "eng_Latn": "eng_Latn",  # English
            "zho_Hans": "zho_Hans",  # Chinese Simplified
            "zho_Hant": "zho_Hant",  # Chinese Traditional
            "jpn_Jpan": "jpn_Jpan",  # Japanese
            "kor_Hang": "kor_Hang",  # Korean
        }
        return mapping.get(lang_code, lang_code)
    
    def load_model(self):
        """Explicitly load NLLB model into memory"""
        if self._is_loaded:
            print("   ℹ️ NLLB model already loaded")
            return
        
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"NLLB model not found at {self.model_path}\n"
                f"Please download it with:\n"
                f"huggingface-cli download michaelfeil/ct2fast-nllb-200-distilled-1.3B "
                f"--local-dir {self.model_path}"
            )
        
        try:
            import ctranslate2
            from transformers import AutoTokenizer
            
            print(f"   📦 Loading NLLB model from {self.model_path}...")
            
            # Load CTranslate2 model
            self.translator = ctranslate2.Translator(
                str(self.model_path),
                device="cuda" if self._has_cuda() else "cpu",
                compute_type="int8"
            )
            
            # Load HuggingFace tokenizer (uses tokenizer.json)
            self.sp_model = AutoTokenizer.from_pretrained(str(self.model_path))
            
            self._is_loaded = True
            print(f"   ✅ NLLB loaded successfully")
            
        except Exception as e:
            print(f"   ❌ Failed to load NLLB: {e}")
            raise
    
    def unload_model(self):
        """Explicitly unload model to free VRAM"""
        if not self._is_loaded:
            return
        
        print("   🗑️ Unloading NLLB model...")
        
        self.translator = None
        self.sp_model = None
        self._is_loaded = False
        
        # Force garbage collection and clear CUDA cache
        import gc
        gc.collect()
        
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                print("   ✅ NLLB unloaded, VRAM freed")
        except ImportError:
            print("   ✅ NLLB unloaded")
    
    def _has_cuda(self) -> bool:
        """Check if CUDA is available"""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
    
    def translate_text(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str
    ) -> str:
        """
        Translate single text
        """
        if not text or not text.strip():
            return text
        
        result = self.translate_batch(
            [text],
            src_lang=src_lang,
            tgt_lang=tgt_lang
        )
        return result[0] if result else text
    
    def translate_batch(
        self,
        texts: List[str],
        src_lang: str,
        tgt_lang: str
    ) -> List[str]:
        """
        Translate batch of texts with NLLB
        
        Args:
            texts: List of texts to translate
            src_lang: Source language code (e.g., "tha_Thai", "eng_Latn")
            tgt_lang: Target language code
        
        Returns:
            List of translated texts
        """
        if not texts:
            return []
        
        # Ensure model is loaded
        if not self._is_loaded:
            self.load_model()
        
        try:
            # Map language codes
            nllb_src = self._map_lang_code(src_lang)
            nllb_tgt = self._map_lang_code(tgt_lang)
            
            # Set source and target languages for tokenizer
            self.sp_model.src_lang = nllb_src
            self.sp_model.tgt_lang = nllb_tgt
            
            # Prepare source tokens
            source_tokens = []
            for text in texts:
                if not text or not text.strip():
                    source_tokens.append([])
                    continue
                
                # Tokenize with language tag (tokenizer handles it automatically)
                encoded = self.sp_model.encode(text, add_special_tokens=True)
                # Convert IDs to token strings for CTranslate2
                tokens = self.sp_model.convert_ids_to_tokens(encoded)
                source_tokens.append(tokens)
            
            # Translate with CTranslate2
            # IMPORTANT: Must specify target_prefix with target language tag!
            results = self.translator.translate_batch(
                source_tokens,
                target_prefix=[[nllb_tgt]] * len(source_tokens),  # ← บอก CTranslate2 ว่าต้องแปลเป็นภาษาอะไร
                beam_size=5,             # ✅ เพิ่มจาก 4 → 5 เพื่อหาคำแปลที่ดีกว่า
                max_input_length=1024,   # ✅ เพิ่มจาก 512 → 1024 สำหรับย่อหน้ายาว
                max_decoding_length=1024,  # ✅ เพิ่มจาก 768 → 1024 เพื่อป้องกันตัดคำ
                repetition_penalty=1.2,  # ป้องกันการซ้ำคำ (ค่าสูง = ลงโทษการซ้ำมากขึ้น)
                no_repeat_ngram_size=3   # ห้ามซ้ำ 3-gram เหมือนกัน
            )
            
            # Decode translations
            translations = []
            for i, result in enumerate(results):
                if not source_tokens[i]:
                    translations.append(texts[i])
                    continue
                
                # Get token strings from result
                tokens = result.hypotheses[0]
                
                # Convert tokens back to IDs for decoding
                try:
                    token_ids = self.sp_model.convert_tokens_to_ids(tokens)
                    # Decode with tokenizer
                    translated = self.sp_model.decode(token_ids, skip_special_tokens=True)
                    translations.append(translated)
                except Exception as decode_error:
                    print(f"   ⚠️ Decode error for text {i+1}: {decode_error}")
                    # Fallback: return original
                    translations.append(texts[i])
            
            return translations
            
        except Exception as e:
            print(f"   ⚠️ NLLB translation error: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to original texts
            return texts


# Singleton instance
nllb_translator = NLLBTranslator()
