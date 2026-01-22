"""
Qwen Refiner Module
Refines NLLB translations using Qwen2.5 model
"""
import requests
import re
from typing import List


def refine_batch_qwen(
    nllb_texts: List[str],
    target_lang: str,
    ollama_url: str,
    model_name: str = "qwen2.5:3b"
) -> List[str]:
    """
    เกลาคำแปลจาก NLLB ด้วย Qwen2.5 (Batch) - Improved
    """
    if not nllb_texts:
        return []
    
    lang_names = {
        "eng_Latn": "English",
        "tha_Thai": "Thai",
        "zho_Hans": "Chinese",
        "jpn_Jpan": "Japanese",
        "kor_Hang": "Korean",
    }
    target_name = lang_names.get(target_lang, target_lang)
    
    # Build prompt
    lines_text = []
    safe_target = target_name.upper()  # ใช้ตัวพิมพ์ใหญ่เพื่อชัดเจน
    
    for idx, text in enumerate(nllb_texts):
        lines_text.append(f"###BLOCK{idx + 1}### {text}")
    
    combined_text = "\n".join(lines_text)
    
    # Qwen Refine Prompt (IMPROVED)
    prompt = (
        f"You are a professional {safe_target} translator.\n\n"
        f"Below are machine-translated {safe_target} texts. Your task is to refine them to sound more natural and fluent in {safe_target}.\n\n"
        "CRITICAL RULES:\n"
        "1. Keep ALL ###BLOCKn### markers in your output\n"
        f"2. Output ONLY the refined {safe_target} translation for each block, no explanations\n"
        "3. Do NOT add English commentary or notes\n"
        f"4. Each block must remain in {safe_target} language\n\n"
        "Example:\n"
        "Input: ###BLOCK1### ฉันชอบกินข้าว\n"
        "Output: ###BLOCK1### ฉันชอบทานข้าว\n\n"
        f"Refine the following {safe_target} texts:\n{combined_text}"
    )
    
    print(f"   ✨ Refining with Qwen ({len(nllb_texts)} blocks)...")
    
    try:
        api_url = f"{ollama_url}/api/generate"
        resp = requests.post(
            api_url,
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 4096}
            },
            timeout=180
        )
        
        if resp.status_code == 200:
            response_text = resp.json().get("response", "").strip()
            
            # Extract refined translations
            results = [""] * len(nllb_texts)
            for i in range(len(nllb_texts)):
                match = re.search(rf"###BLOCK{i+1}###\s*(.*?)(?=\s*###BLOCK{i+2}###|$)", response_text, re.DOTALL)
                if match:
                    block_content = match.group(1).strip()
                    # Cleanup
                    block_content = re.sub(r'^(Refined|Output|Translation|Result):\s*', '', block_content, flags=re.IGNORECASE)
                    block_content = re.sub(r'^\*+|\*+$', '', block_content)
                    
                    # ✅ CRITICAL: Reject if contains English explanation
                    if re.search(r'\b(refined version|more natural|sounds better|I made|I changed)\b', block_content, re.IGNORECASE):
                        print(f"   ⚠️ Qwen Block {i+1}: Rejected English explanation")
                        results[i] = ""  # Mark as failed
                    else:
                        results[i] = block_content.strip()
                else:
                    print(f"   ⚠️ Qwen Block {i+1} not found in response")
            
            # Fallback: use NLLB if Qwen failed
            for i, res in enumerate(results):
                if not res.strip():
                    results[i] = nllb_texts[i]
            
            return results
        else:
            print(f"   ❌ Qwen API Error: {resp.status_code}")
            return nllb_texts
            
    except Exception as e:
        print(f"⚠️ Qwen refine error: {e}")
        return nllb_texts
