
import requests
import re
import time
from typing import List, Dict
from app.config import settings

# Import translation modules
from app.services.translation.typhoon_direct import translate_batch_typhoon as typhoon_translate
from app.services.translation.qwen_refiner import refine_batch_qwen as qwen_refine
from app.services.translation.gemma_refiner import refine_batch_gemma as gemma_refine
from app.services.translation.llama_refiner import refine_batch_llama as llama_refine

class LLMService:
    def __init__(self):
        self.url = f"{settings.OLLAMA_URL}/api/generate"
        self.model = settings.TRANSLATION_MODEL
        self._current_loaded_model = None  # Track currently loaded model
    
    def unload_model(self, model_name: str = None):
        """
        Unload model from GPU to free VRAM
        Uses Ollama's keep_alive=0 to immediately unload
        """
        target = model_name or self._current_loaded_model
        if not target:
            return
        
        try:
            print(f"   🔄 Unloading model {target} from GPU...")
            resp = requests.post(
                self.url,
                json={
                    "model": target,
                    "keep_alive": 0  # Immediately unload
                },
                timeout=30
            )
            if resp.status_code == 200:
                print(f"   ✅ Model {target} unloaded")
                self._current_loaded_model = None
            else:
                print(f"   ⚠️ Failed to unload: {resp.status_code}")
        except Exception as e:
            print(f"   ⚠️ Unload error: {e}")
    
    def set_model(self, model_name: str):
        """
        Set new model and unload previous one if different
        """
        if self._current_loaded_model and self._current_loaded_model != model_name:
            self.unload_model(self._current_loaded_model)
        self.model = model_name
        self._current_loaded_model = model_name
    
    def _get_lang_name(self, lang_code: str) -> str:
        """Map language code to human-readable name"""
        lang_names = {
            "eng_Latn": "English",
            "tha_Thai": "Thai",
            "zho_Hans": "Chinese",
            "jpn_Jpan": "Japanese",
            "kor_Hang": "Korean",
        }
        return lang_names.get(lang_code, lang_code)
    
    def detect_language(self, text: str) -> str:
        """
        Detect language using LLM (More robust than regex)
        """
        if not text or len(text.strip()) < 5:
            return "eng_Latn"
            
        prompt = (
            "Identify the language of the following text.\n"
            "Return ONLY the standardized code from this list:\n"
            "- eng_Latn (English)\n"
            "- tha_Thai (Thai)\n"
            "- jpn_Jpan (Japanese)\n"
            "- zho_Hans (Chinese)\n"
            "- kor_Hang (Korean)\n\n"
            "If unsure, return 'eng_Latn'.\n"
            "Do not explain. Return ONLY the code.\n\n"
            f"Text: \"{text[:500]}\""
        )
        
        try:
            print(f"   🔍 Asking LLM to detect language...")
            resp = requests.post(
                self.url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 10}
                },
                timeout=30
            )
            
            if resp.status_code == 200:
                result = resp.json().get("response", "").strip()
                # Clean up response
                match = re.search(r'([a-z]{3}_[A-Za-z]{4})', result)
                if match:
                    return match.group(1)
                
                # Fallback mapping if LLM returns name
                result_lower = result.lower()
                if "thai" in result_lower: return "tha_Thai"
                if "japan" in result_lower: return "jpn_Jpan"
                if "chin" in result_lower: return "zho_Hans"
                if "korea" in result_lower: return "kor_Hang"
                
                return "eng_Latn"
            else:
                print(f"   ⚠️ Detect Lang API Error: {resp.status_code}")
        except Exception as e:
            print(f"   ⚠️ Detect Lang Error: {e}")
            
        return "eng_Latn"
    
    def translate_batch_llm(self, texts: List[str], target_lang: str, src_lang: str = "tha_Thai") -> List[str]:
        """
        แปล batch (รองรับทุก LLM: Qwen, Gemma, Llama)
        """
        if not texts:
            return []
        
        lang_names = {
            "eng_Latn": "English",
            "tha_Thai": "Thai",
            "zho_Hans": "Chinese",
            "jpn_Jpan": "Japanese",
            "kor_Hang": "Korean",
        }
        target_name = lang_names.get(target_lang, target_lang)
        
        lines_text = []
        for idx, text in enumerate(texts):
            lines_text.append(f"###BLOCK{idx + 1}### {text}")
        
        combined_text = "\n".join(lines_text)
        
        # Generic Batch Prompt (works for all models)
        prompt = (
            f"Translate the following text to {target_name}.\n"
            "Do not translate proper names (preserve them in original language).\n"
            "Output ONLY the translation with the same ###BLOCKn### markers, no explanations.\n\n"
            f"{combined_text}\n"
        )
        
        print(f"   📤 Sending Batch Prompt ({self.model} - {len(texts)} blocks)...")
        
        try:
            resp = requests.post(
                self.url,
                json={
                    "model": self.model,  # Auto-use correct model
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 4096}
                },
                timeout=180
            )
            
            if resp.status_code == 200:
                response_text = resp.json().get("response", "").strip()
                
                # Extract translations using regex
                results = [""] * len(texts)
                for i in range(len(texts)):
                    match = re.search(rf"###BLOCK{i+1}###\s*(.*?)(?=\s*###BLOCK{i+2}###|$)", response_text, re.DOTALL)
                    if match:
                        block_content = match.group(1).strip()
                        # Clean up common prefixes/suffixes from LLM
                        block_content = re.sub(r'^(Here is the translation:|Translation:|Output:)\s*', '', block_content, flags=re.IGNORECASE)
                        block_content = re.sub(r'^\*+|\*+$', '', block_content) # Remove leading/trailing asterisks
                        results[i] = block_content.strip()
                    else:
                        print(f"   ⚠️ Block {i+1} not found in response.")
                
                # CRITICAL CHECK: Reject Chinese output if target is not Chinese/Japanese
                if target_lang not in ["zho_Hans", "zho_Hant", "jpn_Jpan"]:
                    for i, res in enumerate(results):
                        if re.search(r'[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]', res):
                            print(f"   ⚠️ Batch: Rejected Chinese output for block {i+1}: {res[:50]}...")
                            results[i] = "" # Clear the result if it's Chinese
                
                return results
            else:
                print(f"   ❌ API Error: {resp.status_code} - {resp.text}")
                
        except Exception as e:
            print(f"⚠️ Batch LLM error: {e}")
        
        return [""] * len(texts)
    
    # ====== Delegation Methods to Translation Modules ======
    
    def translate_batch_typhoon(self, texts: List[str], target_lang: str, src_lang: str = "tha_Thai", job_status: dict = None, job_id: str = None) -> List[str]:
        """Delegate to typhoon_direct module"""
        return typhoon_translate(texts, target_lang, src_lang, self.url, self.model, job_status, job_id)
    
    def refine_batch_qwen(self, texts: List[str], target_lang: str) -> List[str]:
        """Delegate to qwen_refiner module"""
        return qwen_refine(texts, target_lang, self.url, self.model)
    
    def refine_batch_gemma(self, texts: List[str], target_lang: str) -> List[str]:
        """Delegate to gemma_refiner module"""
        return gemma_refine(texts, target_lang, self.url, self.model)
    
    def refine_batch_llama(self, texts: List[str], target_lang: str) -> List[str]:
        """Delegate to llama_refiner module"""
        return llama_refine(texts, target_lang, self.url, self.model)


# Singleton instance
llm_service = LLMService()
