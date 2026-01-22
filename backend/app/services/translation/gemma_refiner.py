"""
Gemma Refiner Module  
Refines NLLB translations using Gemma model
"""
import requests
import re
from typing import List


def refine_batch_gemma(
    nllb_texts: List[str],
    target_lang: str,
    ollama_url: str,
    model_name: str = "gemma2:2b"
) -> List[str]:
    """
    เกลาคำแปลจาก NLLB ด้วย Gemma (Batch) - Improved
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
    
    # Build batch prompt
    lines_text = []
    for idx, text in enumerate(nllb_texts):
        lines_text.append(f"###BLOCK{idx + 1}### {text}")
    
    combined_text = "\n".join(lines_text)
    
    # Gemma Refine Prompt
    prompt = (
        f"You are a professional {target_name} translator.\n\n"
        f"Below are machine-translated {target_name} texts. Refine them to sound more natural and fluent.\n\n"
        "CRITICAL RULES:\n"
        "1. Keep ALL ###BLOCKn### markers in your output\n"
        f"2. Output ONLY the refined {target_name} translation for each block\n"
        "3. Do NOT add English commentary or explanations\n"
        "4. Focus on naturalness and fluency\n\n"
        f"Refine the following {target_name} texts:\n{combined_text}"
    )
    
    print(f"   ✨ Refining with Gemma ({len(nllb_texts)} blocks)...")
    
    try:
        api_url = f"{ollama_url}/api/generate"
        resp = requests.post(
            api_url,
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 4096}
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
                    block_content = re.sub(r'^(Refined|Output|Translation):\s*', '', block_content, flags=re.IGNORECASE)
                    block_content = re.sub(r'^\*+|\*+$', '', block_content)
                    
                    # Reject if contains explanation
                    if re.search(r'\b(refined version|more natural|I made|I changed)\b', block_content, re.IGNORECASE):
                        print(f"   ⚠️ Gemma Block {i+1}: Rejected English explanation")
                        results[i] = ""
                    else:
                        results[i] = block_content.strip()
                else:
                    print(f"   ⚠️ Gemma Block {i+1} not found in response")
            
            # Fallback: use NLLB if Gemma failed
            for i, res in enumerate(results):
                if not res.strip():
                    results[i] = nllb_texts[i]
            
            return results
        else:
            print(f"   ❌ Gemma API Error: {resp.status_code}")
            return nllb_texts
            
    except Exception as e:
        print(f"⚠️ Gemma refine error: {e}")
        return nllb_texts
