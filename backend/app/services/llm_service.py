
import requests
import re
import time
from typing import List, Dict
from app.config import settings

# Import translation modules
from app.services.translation.typhoon_direct import translate_batch_typhoon as typhoon_translate

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
        Dynamic detection: Returns standard code (e.g. eng_Latn, tha_Thai, fra_Latn)
        """
        if not text or len(text.strip()) < 5:
            return "eng_Latn"
            
        # Dynamic prompt - ask LLM to identify and return standard code
        prompt = (
            "Identify the language of the following text.\n"
            "Return ONLY the standardized ISO 639-3 code (e.g., eng_Latn, tha_Thai, jpn_Jpan, zho_Hans, fra_Latn, spa_Latn, etc.).\n"
            "If the script is Latin, append '_Latn'. If Thai, '_Thai'. If unsure, return 'eng_Latn'.\n"
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
                timeout=120  # ✅ Increased to 120s to allow model loading time
            )
            
            if resp.status_code == 200:
                result = resp.json().get("response", "").strip()
                
                # Check if result looks like a code (e.g. xyz_Script)
                # Matches: 3 lowercase letters, underscore, 4 letters (Script)
                # Or just 2-3 letters (ISO 639-1/2) fallback
                match = re.search(r'([a-z]{2,3}_[A-Za-z]{4})', result)
                if match:
                    return match.group(1)
                
                # Fallback: if LLM returns just "Thai" or "English"
                # We do a basic mapping for common ones, but accept others if we can normalize
                result_lower = result.lower()
                
                # Dynamic mapping helper could be here, but for now specific overrides
                if "thai" in result_lower: return "tha_Thai"
                if "english" in result_lower: return "eng_Latn"
                if "japan" in result_lower: return "jpn_Jpan"
                if "chinese" in result_lower:
                    return "zho_Hans" if "simplified" in result_lower else "zho_Hant" if "traditional" in result_lower else "zho_Hans"
                if "korea" in result_lower: return "kor_Hang"
                
                # If it returns a simple code like "en", "th"
                if re.match(r'^[a-z]{2,3}$', result_lower):
                    # Basic mapping
                    simple_map = {"en": "eng_Latn", "th": "tha_Thai", "ja": "jpn_Jpan", "zh": "zho_Hans", "ko": "kor_Hang"}
                    return simple_map.get(result_lower, f"{result_lower}_Latn") # Default to Latn script if unknown

                return "eng_Latn"
            else:
                print(f"   ⚠️ Detect Lang API Error: {resp.status_code}")
        except Exception as e:
            print(f"   ⚠️ Detect Lang Error: {e}")
            
        return "eng_Latn"
    
    def translate_batch_llm(self, texts: List[str], target_lang: str, src_lang: str = "tha_Thai") -> List[str]:
        """
        แปล batch (รองรับทุก LLM: Qwen, Gemma, Llama)
        Dynamic target language support
        """
        if not texts:
            return []
        
        # Use target_lang code directly in prompt, or try to humanize it slightly if needed
        # But mostly LLMs understand "Translate to tha_Thai" or just "Translate to Thai"
        # Let's try to pass the code directly if it's standard, or use it as name
        target_name = target_lang
        
        # Simple heuristic to make it friendlier if it's a known code style
        if "_" in target_lang:
            # e.g. tha_Thai -> Thai
            try:
                # This is just a helper, detection/translation should be robust
                # If we want purely dynamic, we can just say "Translate to {target_lang}"
                # But "Translate to tha_Thai" might be weird for some models.
                # Let's just use the code, Typhoon knows these codes well (FLORES-200).
                pass
            except:
                pass
        
        lines_text = []
        for idx, text in enumerate(texts):
            lines_text.append(f"###BLOCK{idx + 1}### {text}")
        
        combined_text = "\n".join(lines_text)
        src_name = self._get_lang_name(src_lang)
        
        # Generic Batch Prompt (works for all models)
        prompt = (
            f"Translate the following text from {src_name} to {target_name}.\n"
            "CRITICAL RULES:\n"
            "1. Output ONLY the translation with the same ###BLOCKn### markers.\n"
            "2. Translate EVERY sentence completely. Do NOT summarize.\n"
            "3. Do not translate proper names (preserve them in original language).\n"
            "4. Do NOT repeat the input text or output looped nonsense.\n"
            "5. If the input is nonsense, return the input as is.\n\n"
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
                
                # CRITICAL CHECK: Generic Script Validation (Same as Typhoon)
                # Ban any script that is NOT the target script.
                script_definitions = [
                    {"code": "tha", "name": "Thai", "start": '\u0e00', "end": '\u0e7f'},
                    {"code": "kor", "name": "Korean", "start": '\uac00', "end": '\ud7af'},
                    {"code": "jpn", "name": "Japanese (Kana)", "start": '\u3040', "end": '\u30ff'},
                    {"code": "zho", "name": "Chinese", "start": '\u4e00', "end": '\u9fff'},
                    {"code": "lao", "name": "Lao", "start": '\u0e80', "end": '\u0eff'},
                    {"code": "khm", "name": "Khmer", "start": '\u1780', "end": '\u17ff'},
                    {"code": "mya", "name": "Burmese", "start": '\u1000', "end": '\u109f'},
                ]

                for i, res in enumerate(results):
                    if not res: continue
                    
                    # 1. Reject Chinese output if target is not Chinese/Japanese
                    if target_lang not in ["zho_Hans", "zho_Hant", "jpn_Jpan"]:
                        if re.search(r'[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]', res):
                            print(f"   ⚠️ Batch: Rejected Chinese output for block {i+1}")
                            results[i] = ""
                            continue

                    # 2. Generic Script Validation
                    for script in script_definitions:
                        # Skip if this script IS the target language
                        if script["code"] in target_lang.lower():
                            continue
                        
                        # Special check: Allow Chinese in Japanese
                        if "jpn" in target_lang.lower() and script["code"] == "zho":
                            continue

                        # Check for banned script chars
                        count = sum(1 for c in res if script["start"] <= c <= script["end"])
                        if count > 0:
                            print(f"   ⚠️ Batch: Rejected {script['name']} output for block {i+1} (Source Leak)")
                            results[i] = "" # INVALID -> Trigger fallback failure
                            break

                return results
            else:
                print(f"   ❌ API Error: {resp.status_code} - {resp.text}")
                
        except Exception as e:
            print(f"⚠️ Batch LLM error: {e}")
        
        return [""] * len(texts)
    
    # ====== Delegation Methods to Translation Modules ======
    
    def translate_batch_typhoon(self, texts: List[str], target_lang: str, src_lang: str = "tha_Thai", job_status: dict = None, job_id: str = None) -> (List[str], List[int]):
        """Delegate to typhoon_direct module. Returns (results, failed_indices)"""
        return typhoon_translate(texts, target_lang, src_lang, self.url, self.model, job_status, job_id)


# Singleton instance
llm_service = LLMService()
