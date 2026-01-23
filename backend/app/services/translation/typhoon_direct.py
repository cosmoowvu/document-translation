"""
Typhoon Direct Translation Module
Handles direct translation using Typhoon Translate 1.5 (4B)
Optimized for Thai ↔ English translation
"""
import requests
import re
from typing import List, Tuple


def remove_duplicate_blocks(response_text: str) -> Tuple[str, int]:
    """
    ตรวจสอบและลบ duplicate ###BLOCKn### markers ออกจาก response
    Returns: (cleaned_response, num_duplicates_removed)
    """
    # หา all blocks ที่มีใน response
    block_pattern = r'(###BLOCK\d+###.*?)(?=###BLOCK\d+###|$)'
    all_blocks = re.findall(block_pattern, response_text, re.DOTALL)
    
    if not all_blocks:
        return response_text, 0
    
    # Track unique blocks by block number
    seen_blocks = {}
    duplicates = 0
    
    for block in all_blocks:
        # Extract block number
        num_match = re.search(r'###BLOCK(\d+)###', block)
        if num_match:
            block_num = int(num_match.group(1))
            if block_num not in seen_blocks:
                seen_blocks[block_num] = block
            else:
                duplicates += 1
    
    # Reconstruct response with unique blocks only (in order)
    if duplicates > 0:
        sorted_blocks = [seen_blocks[num] for num in sorted(seen_blocks.keys())]
        cleaned = '\n'.join(sorted_blocks)
        return cleaned, duplicates
    
    return response_text, 0


def translate_batch_typhoon(
    texts: List[str],
    target_lang: str,
    src_lang: str,
    ollama_url: str,
    model_name: str,
    job_status: dict = None,
    job_id: str = None
) -> List[str]:
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
    
    # ✅ Check cancelled flag before translation
    if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
        print("   🚫 Job cancelled - stopping Typhoon translation")
        return [""] * len(texts)
    
    max_retries = 1  # Retry once if >30% blocks missing
    
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                ollama_url,  # Already has /api/generate from llm_service.url
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 4096}
                },
                timeout=180
            )
            
            if resp.status_code == 200:
                response_text = resp.json().get("response", "").strip()
                
                # ✅ Debug: Check for duplicate blocks
                if '###BLOCK1###' in response_text:
                    block1_count = response_text.count('###BLOCK1###')
                    if block1_count > 1:
                        print(f"   🔍 DEBUG: Found {block1_count} occurrences of BLOCK1 in response")
                
                # ✅ Remove duplicate blocks before parsing
                cleaned_response, num_duplicates = remove_duplicate_blocks(response_text)
                if num_duplicates > 0:
                    print(f"   ⚠️ Removed {num_duplicates} duplicate blocks from Typhoon response")
                
                # Extract translations using regex from cleaned response
                results = [""] * len(texts)
                missing_blocks = []
                for i in range(len(texts)):
                    match = re.search(rf"###BLOCK{i+1}###\s*(.*?)(?=\s*###BLOCK{i+2}###|$)", cleaned_response, re.DOTALL)
                    if match:
                        block_content = match.group(1).strip()
                        # Clean up common prefixes/suffixes from LLM
                        block_content = re.sub(r'^(Here is the translation:|Translation:|Output:)\s*', '', block_content, flags=re.IGNORECASE)
                        block_content = re.sub(r'^\*+|\*+$', '', block_content)
                        results[i] = block_content.strip()
                    else:
                        missing_blocks.append(i)
                
                # ✅ Retry logic: if >30% blocks missing, retry entire batch once
                missing_rate = len(missing_blocks) / len(texts) if texts else 0
                if missing_blocks and missing_rate > 0.3 and attempt < max_retries:
                    print(f"   🔄 Retry {attempt + 1}/{max_retries}: {len(missing_blocks)}/{len(texts)} blocks missing ({missing_rate*100:.0f}%)")
                    continue  # Retry with same prompt
                
                # Fill missing blocks with original text
                for i in missing_blocks:
                    print(f"   ⚠️ Block {i+1} not found, using original text")
                    results[i] = texts[i]
                
                # Log summary
                if missing_blocks:
                    print(f"   ⚠️ Typhoon: {len(missing_blocks)}/{len(texts)} blocks fell back to original")
                
                return results
            else:
                print(f"   ❌ API Error: {resp.status_code} - {resp.text}")
                
        except Exception as e:
            print(f"⚠️ Typhoon error (attempt {attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                print(f"   🔄 Retrying...")
                continue
    
    return [""] * len(texts)
