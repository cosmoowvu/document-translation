
import requests
import re
import time
from typing import List, Dict
from app.config import settings

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
            "eng_Latn": "English", # Changed from "Thai" to "English" to match common usage for eng_Latn
            "tha_Thai": "Thai",
            "zho_Hans": "Chinese",
            "zho_Hant": "Chinese", # Added Traditional Chinese
            "jpn_Jpan": "Japanese",
            "kor_Hang": "Korean",
        }
        return lang_names.get(lang_code, lang_code) # Changed default to lang_code for robustness
    
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
    
    def translate_batch_typhoon(self, texts: List[str], target_lang: str, src_lang: str = "tha_Thai") -> List[str]:
        """
        แปลโดยตรงด้วย Typhoon Translate 1.5 (4B)
        - Optimized for Thai ↔ English translation
        - Uses simple prompt format recommended by scb10x
        """
        if not texts:
            return []
        
        lang_names = {
            "eng_Latn": "English",
            "tha_Thai": "Thai",
        }
        target_name = lang_names.get(target_lang, "English" if target_lang != "tha_Thai" else "Thai")
        
        # Build batch prompt with markers
        lines_text = []
        for idx, text in enumerate(texts):
            lines_text.append(f"###BLOCK{idx + 1}### {text}")
        
        combined_text = "\n".join(lines_text)
        num_blocks = len(texts)
        
        # Typhoon Translate prompt - IMPROVED to force separate block output
        prompt = (
            f"Translate each block below into {target_name}.\n\n"
            "CRITICAL RULES:\n"
            f"1. You MUST output exactly {num_blocks} blocks with markers ###BLOCK1### to ###BLOCK{num_blocks}###\n"
            "2. Translate each block SEPARATELY - do NOT merge blocks together\n"
            "3. Each block's translation must appear after its ###BLOCKn### marker\n"
            "4. Output ONLY the translations, no explanations\n\n"
            "Example format:\n"
            "###BLOCK1### [translation of block 1]\n"
            "###BLOCK2### [translation of block 2]\n\n"
            f"Input ({num_blocks} blocks):\n{combined_text}\n\n"
            f"Output ({num_blocks} blocks in {target_name}):"
        )
        
        print(f"   📤 Sending Batch Prompt (Typhoon - {len(texts)} blocks)...")
        
        try:
            resp = requests.post(
                self.url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 4096}  # Low temp for translation accuracy
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
                        block_content = re.sub(r'^\*+|\*+$', '', block_content)
                        results[i] = block_content.strip()
                    else:
                        print(f"   ⚠️ Block {i+1} not found in response.")
                
                return results
            else:
                print(f"   ❌ API Error: {resp.status_code} - {resp.text}")
                
        except Exception as e:
            print(f"⚠️ Typhoon translation error: {e}")
        
        return [""] * len(texts)
    
    def refine_batch_qwen(self, texts: List[str], target_lang: str) -> List[str]:
        """เกลาคำแปลจาก NLLB ด้วย Qwen2.5 (Batch) - Improved"""
        if not texts:
            return []
        
        target_name = self._get_lang_name(target_lang)
        
        # Build batch prompt
        lines_text = []
        for idx, text in enumerate(texts):
            lines_text.append(f"###BLOCK{idx + 1}### {text}")
        
        combined_text = "\n".join(lines_text)
        
        # Determine allowed languages
        is_cjk_target = target_lang in ["zho_Hans", "zho_Hant", "jpn_Jpan", "kor_Hang"]
        language_constraint = ""
        if not is_cjk_target:
            language_constraint = (
                "6. CRITICAL: DO NOT output Chinese, Japanese, or Korean characters\n"
                "   - Only use the target language alphabet/script\n"
                "   - If you accidentally use CJK characters, the output will be REJECTED\n\n"
            )
        
        # Improved Qwen refine prompt - MORE AGGRESSIVE
        prompt = (
            f"You are an expert translator refining machine-translated {target_name} text.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. The input is from NLLB-200 machine translation - it's often awkward and unnatural\n"
            "2. You MUST significantly improve the text to sound like a native speaker wrote it\n"
            "3. Fix awkward word choices, improve sentence structure, use natural phrasing\n"
            "4. Keep the exact same meaning, but express it more naturally\n"
            "5. Remove any mechanical/robotic translation artifacts\n"
            "6. If something is unclear, keep it unclear. Do not guess.\n"  # ✅ เพิ่มกฎห้ามเดา
            "7. Do not add any details not present in the input.\n"  # ✅ เพิ่มกฎห้ามเติม
            f"{language_constraint}"
            "Examples of good improvements:\n"
            "- Awkward: 'เขาทำการเดินไป' → Natural: 'เขาเดินไป'\n"
            "- Awkward: 'สิ่งของต่างๆ' → Natural: 'ของต่างๆ' or 'สิ่งของ'\n"
            "- Awkward: 'ทำให้เกิดการ' → Natural: 'ทำให้' or 'ก่อให้เกิด'\n\n"
            "Output format: Use the same ###BLOCKn### markers, NO explanations.\n\n"
            f"NLLB translation output (needs refinement):\n{combined_text}\n\n"
            f"Your refined, natural {target_name} text:"
        )
        
        print(f"   ✨ Refining with Qwen ({len(texts)} blocks)...")
        
        try:
            resp = requests.post(
                self.url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.5, "num_predict": 4096}  #  ✅ เพิ่มเป็น 0.5 เพื่อความเป็นธรรมชาติ
                },
                timeout=180  # ← เพิ่มเป็น 5 นาที (experiment)  # ← เพิ่มเป็น 3 นาที
            )
            
            if resp.status_code == 200:
                response_text = resp.json().get("response", "").strip()
                
                # Extract refined translations
                results = [""] * len(texts)
                for i in range(len(texts)):
                    match = re.search(rf"###BLOCK{i+1}###\s*(.*?)(?=\s*###BLOCK{i+2}###|$)", response_text, re.DOTALL)
                    if match:
                        refined = match.group(1).strip()
                        
                        # Validate: check if output is different enough from input
                        if not refined or refined == texts[i]:
                            print(f"   ⚠️ Block {i+1}: LLM output identical to input, using NLLB")
                            results[i] = texts[i]
                            continue
                        
                        # Validate: check for unwanted CJK characters
                        if not is_cjk_target:
                            # Check for Chinese/Japanese/Korean characters
                            if re.search(r'[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF]', refined):
                                print(f"   ⚠️ Block {i+1}: Unwanted CJK characters detected, using NLLB")
                                print(f"      Rejected: {refined[:80]}...")
                                results[i] = texts[i]
                                continue
                        
                        results[i] = refined
                    else:
                        print(f"   ⚠️ Block {i+1}: No match found, using NLLB")
                        results[i] = texts[i]  # Fallback to NLLB result
                
                return results
                
        except Exception as e:
            print(f"⚠️ Qwen refine error: {e}")
        
        return texts  # Fallback: return NLLB results
    
    def refine_batch_gemma(self, texts: List[str], target_lang: str) -> List[str]:
        """เกลาคำแปลจาก NLLB ด้วย Gemma (Batch) - Improved"""
        if not texts:
            return []
        
        target_name = self._get_lang_name(target_lang)
        
        # Build batch prompt
        lines_text = []
        for idx, text in enumerate(texts):
            lines_text.append(f"###BLOCK{idx + 1}### {text}")
        
        combined_text = "\n".join(lines_text)
        
        # Gemma refine prompt - Aggressive (Always Improve)
        prompt = (
            f"You are improving {target_name} text from machine translation.\n\n"
            f"Your task: Make EVERY sentence sound natural and fluent, like a native speaker wrote it.\n\n"
            f"Common machine translation problems to fix:\n"
            f"- Awkward word order or phrasing\n"
            f"- Overly literal translations that don't sound natural\n"
            f"- Missing connectors or particles\n"
            f"- Unnatural vocabulary choices\n"
            f"- Choppy or robotic tone\n\n"
            f"CRITICAL RULES:\n"
            f"1. Input is {target_name} - Output MUST be {target_name} (DO NOT translate to English!)\n"
            f"2. Improve EVERY sentence - make it flow naturally\n"
            f"3. Keep the exact same meaning - don't add or remove information\n"
            f"4. Output ONLY the improved text with ###BLOCKn### markers\n\n"
            f"Input {target_name} text:\n"
            f"{combined_text}\n\n"
            f"Improved {target_name} text (natural, fluent, same meaning):"
        )
        
        print(f"   ✨ Refining with Gemma ({len(texts)} blocks)...")
        
        try:
            resp = requests.post(
                self.url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.5, "num_predict": 4096}  # ✅ ลดจาก 0.6 → 0.3 เพื่อลดการเดา
                },
                timeout=180  # ← เพิ่มเป็น 5 นาที (experiment)  # ← เพิ่มเป็น 3 นาที
            )
            
            if resp.status_code == 200:
                response_text = resp.json().get("response", "").strip()
                
                # Extract refined translations
                results = [""] * len(texts)
                for i in range(len(texts)):
                    match = re.search(rf"###BLOCK{i+1}###\s*(.*?)(?=\s*###BLOCK{i+2}###|$)", response_text, re.DOTALL)
                    if match:
                        refined = match.group(1).strip()
                        
                        # ✅ Clean up Gemma's extra explanations (English text)
                        # Remove explanations that start after Thai text
                        refined = re.sub(r'I made some changes.*$', '', refined, flags=re.DOTALL | re.IGNORECASE)
                        refined = re.sub(r'Here\'s a brief.*$', '', refined, flags=re.DOTALL | re.IGNORECASE)
                        refined = re.sub(r'\*\*Explanation[^*]*\*\*.*$', '', refined, flags=re.DOTALL | re.IGNORECASE)
                        refined = re.sub(r'Let me know.*$', '', refined, flags=re.DOTALL | re.IGNORECASE)
                        refined = re.sub(r'\*\*[A-Za-z\s:]+\*\*.*$', '', refined, flags=re.DOTALL)  # Remove **English headings**
                        refined = re.sub(r'^[A-Za-z\s:]+:\s*', '', refined, flags=re.MULTILINE)  # Remove "Consistency:", etc.
                        
                        # Remove any line/paragraph that starts with bullet points and English
                        refined = re.sub(r'(\n\s*\*\s+In BLOCK.*$)', '', refined, flags=re.DOTALL)
                        
                        # Remove trailing English sentences (lines starting with capital letters)
                        lines = refined.split('\n')
                        clean_lines = []
                        for line in lines:
                            line_stripped = line.strip()
                            # Skip if line is mostly English (starts with English word)
                            if line_stripped and re.match(r'^[A-Z][a-z]+', line_stripped):
                                continue
                            clean_lines.append(line)
                        refined = '\n'.join(clean_lines).strip()
                        
                        # Validate: check if output is different enough from input
                        if refined and refined != texts[i]:
                            results[i] = refined
                        else:
                            print(f"   ⚠️ Block {i+1}: LLM output identical to input, using NLLB")
                            results[i] = texts[i]
                    else:
                        print(f"   ⚠️ Block {i+1}: No match found, using NLLB")
                        results[i] = texts[i]  # Fallback to NLLB result
                
                return results
                
        except Exception as e:
            print(f"⚠️ Gemma refine error: {e}")
        
        return texts  # Fallback: return NLLB results

    def refine_batch_llama(self, texts: List[str], target_lang: str) -> List[str]:
        """เกลาคำแปลจาก NLLB ด้วย Llama 3.2 (Batch)"""
        if not texts:
            return []
        
        target_name = self._get_lang_name(target_lang)
        
        # Build batch prompt
        lines_text = []
        for idx, text in enumerate(texts):
            lines_text.append(f"###BLOCK{idx + 1}### {text}")
        
        combined_text = "\n".join(lines_text)
        
        # Llama refine prompt - Aggressive (Always Improve)
        prompt = (
            f"Improve the following {target_name} translation to make it sound natural and fluent.\n\n"
            f"Your goal: Transform machine translation into text that sounds like a native speaker wrote it.\n\n"
            f"Fix these common problems:\n"
            f"- Awkward phrasing or word order\n"
            f"- Overly literal/stiff translations\n"
            f"- Unnatural word choices\n"
            f"- Choppy sentences that don't flow\n\n"
            f"Rules:\n"
            f"1. Improve EVERY sentence for naturalness and fluency\n"
            f"2. Keep the exact same meaning - don't add or remove information\n"
            f"3. Output ONLY the improved {target_name} text with ###BLOCKn### markers\n\n"
            f"{combined_text}\n\n"
            f"Improved {target_name} text:"
        )
        
        print(f"   ✨ Refining with Llama 3.2 ({len(texts)} blocks)...")
        
        try:
            resp = requests.post(
                self.url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 4096}  # ✅ ลดจาก 0.5 → 0.3 เพื่อลดการเดา
                },
                timeout=180  # ← เพิ่มเป็น 5 นาที (experiment)  # ← เพิ่มเป็น 3 นาที
            )
            
            if resp.status_code == 200:
                response_text = resp.json().get("response", "").strip()
                
                # Extract refined translations
                results = [""] * len(texts)
                for i in range(len(texts)):
                    match = re.search(rf"###BLOCK{i+1}###\s*(.*?)(?=\s*###BLOCK{i+2}###|$)", response_text, re.DOTALL)
                    if match:
                        refined = match.group(1).strip()
                        
                        # ✅ Clean up Llama's extra explanations (English text)
                        # Remove explanations that start after Thai text
                        refined = re.sub(r'I made some changes.*$', '', refined, flags=re.DOTALL | re.IGNORECASE)
                        refined = re.sub(r'Here\'s a brief.*$', '', refined, flags=re.DOTALL | re.IGNORECASE)
                        refined = re.sub(r'\*\*Explanation[^*]*\*\*.*$', '', refined, flags=re.DOTALL | re.IGNORECASE)
                        refined = re.sub(r'Let me know.*$', '', refined, flags=re.DOTALL | re.IGNORECASE)
                        refined = re.sub(r'\*\*[A-Za-z\s:]+\*\*.*$', '', refined, flags=re.DOTALL)  # Remove **English headings**
                        refined = re.sub(r'^[A-Za-z\s:]+:\s*', '', refined, flags=re.MULTILINE)  # Remove "Consistency:", etc.
                        
                        # Remove any line/paragraph that starts with bullet points and English
                        refined = re.sub(r'(\n\s*\*\s+In BLOCK.*$)', '', refined, flags=re.DOTALL)
                        
                        # Remove trailing English sentences (lines starting with capital letters)
                        lines = refined.split('\n')
                        clean_lines = []
                        for line in lines:
                            line_stripped = line.strip()
                            # Skip if line is mostly English (starts with English word)
                            if line_stripped and re.match(r'^[A-Z][a-z]+', line_stripped):
                                continue
                            clean_lines.append(line)
                        refined = '\n'.join(clean_lines).strip()
                        
                        # Validate: check if output is different enough from input
                        if refined and refined != texts[i]:
                            results[i] = refined
                        else:
                            print(f"   ⚠️ Block {i+1}: LLM output identical to input, using NLLB")
                            results[i] = texts[i]
                    else:
                        print(f"   ⚠️ Block {i+1}: No match found, using NLLB")
                        results[i] = texts[i]  # Fallback to NLLB result
                
                return results
                
        except Exception as e:
            print(f"⚠️ Llama refine error: {e}")
        
        return texts  # Fallback: return NLLB results

