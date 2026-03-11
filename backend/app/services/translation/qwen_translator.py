"""
Qwen 2.5 Translation Module
Fallback translator for blocks that Typhoon couldn't translate properly
"""
import requests
import re
from typing import List, Tuple


def translate_blocks_qwen(
    texts: List[str],
    target_lang: str,
    src_lang: str,
    ollama_url: str,
    model_name: str = "qwen2.5:latest",
    job_status: dict = None,
    job_id: str = None
) -> Tuple[List[str], List[int]]:
    """
    Translate using Qwen 2.5 (fallback mode)
    Simpler than Typhoon - no retry logic, single attempt
    
    Returns:
        (results, failed_indices) - indices that still failed after Qwen
    """
    if not texts:
        return [], []
    
    lang_names = {
        "eng_Latn": "English",
        "tha_Thai": "Thai",
        "zho_Hans": "Chinese (Simplified)",
        "zho_Hant": "Chinese (Traditional)",
        "jpn_Jpan": "Japanese",
        "kor_Hang": "Korean",
        "lao_Laoo": "Lao",
        "mya_Mymr": "Burmese",
        "khm_Khmr": "Khmer",
        "vie_Latn": "Vietnamese",
        "ind_Latn": "Indonesian",
        "msa_Latn": "Malay",
    }
    
    target_name = lang_names.get(target_lang, target_lang)
    
    # Build batch prompt (similar to Typhoon)
    lines_text = []
    for idx, text in enumerate(texts):
        lines_text.append(f"###BLOCK{idx + 1}### {text}")
    
    combined_text = "\n".join(lines_text)
    num_blocks = len(texts)
    
    # Simplified prompt for Qwen
    prompt = (
        f"Translate each block from {lang_names.get(src_lang, src_lang)} to {target_name}.\n\n"
        "RULES:\n"
        f"1. Output exactly {num_blocks} blocks with markers ###BLOCK1### to ###BLOCK{num_blocks}###\n"
        "2. Translate EVERYTHING to target language (including proper names)\n"
        "3. Translate ALL text naturally, transcribing proper names phonetically where needed.\n"
        "4. Output ONLY the translations, no explanations\n"
        "5. Stop translating exactly where the original text ends. Do not add any sentences.\n\n"
        f"Input:\n{combined_text}\n\n"
        f"Output ({num_blocks} blocks in {target_name}):"
    )
    
    print(f"   🔄 Qwen Fallback: Translating {len(texts)} blocks...")
    
    # Check cancellation
    if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
        print("   🚫 Job cancelled - stopping Qwen translation")
        return [""] * len(texts), list(range(len(texts)))
    
    # Ensure we use /api/generate endpoint
    if '/api/generate' not in ollama_url:
        base_url = ollama_url.rstrip('/')
        api_url = f"{base_url}/api/generate"
    else:
        api_url = ollama_url
    
    try:
        resp = requests.post(
            api_url,
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 4096,
                    "top_p": 0.9
                }
            },
            timeout=300
        )
        
        if resp.status_code == 200:
            response_text = resp.json().get("response", "").strip()
            
            # Extract blocks
            results = [""] * len(texts)
            missing_blocks = []
            
            for i in range(len(texts)):
                match = re.search(rf"###BLOCK{i+1}###\s*(.*?)(?=\s*###BLOCK{i+2}###|$)", response_text, re.DOTALL)
                if match:
                    block_content = match.group(1).strip()
                    # Clean up
                    block_content = re.sub(r'^(Here is the translation:|Translation:|Output:)\s*', '', block_content, flags=re.IGNORECASE)
                    block_content = re.sub(r'^\*+|\*+$', '', block_content)
                    results[i] = block_content.strip()
                else:
                    missing_blocks.append(i)
                    results[i] = texts[i]  # Fallback to original
            
            if missing_blocks:
                print(f"   ⚠️ Qwen: {len(missing_blocks)}/{len(texts)} blocks missing, using original text")
            else:
                print(f"   ✅ Qwen successfully translated all {len(texts)} blocks")
            
            return results, missing_blocks
        
        else:
            print(f"   ❌ Qwen API error: {resp.status_code} - {resp.text}")
    
    except Exception as e:
        print(f"   ❌ Qwen error: {e}")
    
    # On failure, return original texts
    return texts, list(range(len(texts)))


def _generate_qwen(
    prompt: str,
    ollama_url: str,
    model_name: str,
    temperature: float = 0.1
) -> str:
    """
    Generate raw text from Qwen (helper for specific tasks like Table Translation)
    """
    if '/api/generate' not in ollama_url:
        base_url = ollama_url.rstrip('/')
        api_url = f"{base_url}/api/generate"
    else:
        api_url = ollama_url
        
    try:
        resp = requests.post(
            api_url,
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": 4096,
                    "top_p": 0.9
                }
            },
            timeout=300
        )
        
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
        else:
            print(f"   ❌ Qwen API error: {resp.status_code} - {resp.text}")
            return ""
            
    except Exception as e:
        print(f"   ❌ Qwen request error: {e}")
        return ""
