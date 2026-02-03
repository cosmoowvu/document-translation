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
        "zho_Hans": "Chinese (Simplified)",
        "zho_Hant": "Chinese (Traditional)",
        "jpn_Jpan": "Japanese",
        "kor_Hang": "Korean (Hangul)",
        "lao_Laoo": "Lao",
        "mya_Mymr": "Burmese",
        "khm_Khmr": "Khmer",
        "vie_Latn": "Vietnamese",
        "ind_Latn": "Indonesian",
        "msa_Latn": "Malay",
    }
    # Fallback to English only if target is explicitly English or unknown Latin
    # For others, use the code itself if not in map (better than forcing English)
    target_name = lang_names.get(target_lang, target_lang)
    
    # Build batch prompt with markers
    lines_text = []
    for idx, text in enumerate(texts):
        lines_text.append(f"###BLOCK{idx + 1}### {text}")
    
    combined_text = "\n".join(lines_text)
    num_blocks = len(texts)
    
    # Specialized instruction for Korean
    extra_instruction = ""
    example_section = "Example format:\n###BLOCK1### [translation of block 1]\n###BLOCK2### [translation of block 2]\n\n"
    
    if "kor" in target_lang.lower() or "korean" in target_name.lower():
        extra_instruction = "5. For Korean, you MUST use Hangul script (e.g., 안녕하세요). Do NOT use Latin/Romanization.\n"
        # One-shot example for Korean to force translation behavior
        example_section = (
            "Example:\n"
            "Input:\n###BLOCK1### สวัสดีทักทาย\n"
            "Output:\n###BLOCK1### 안녕하세요\n\n"
        )

    # Typhoon Translate prompt - IMPROVED to force separate block output
    prompt = (
        f"Translate each block below from {lang_names.get(src_lang, src_lang)} into {target_name}.\n\n"
        "CRITICAL RULES:\n"
        f"1. You MUST output exactly {num_blocks} blocks with markers ###BLOCK1### to ###BLOCK{num_blocks}###\n"
        "2. Translate each block SEPARATELY - do NOT merge blocks together\n"
        "3. Each block's translation must appear after its ###BLOCKn### marker\n"
        "4. Output ONLY the translations, no explanations\n"
        f"{extra_instruction}"
        "6. Do NOT return the original source text. You must translate it.\n"
        f"7. Translate ALL text from ANY source language (including mixed languages) into {target_name}. Ensure the entire output is in {target_name} script/language only. Transliterate proper names or technical terms if needed.\n\n"
        f"{example_section}"
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
                ollama_url,
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.6,  #ควบคุมการสุ่มสำหรับการตอบกลับที่สร้างสรรค์มากขึ้น
                        "repeat_penalty": 1.05, #ป้องกันข้อความซ้ำซาก
                        "num_predict": 4096,  #ควบคุมจำนวนคำที่จะสร้าง
                        "top_p": 0.9          #ควบคุมความหลากหลายของการตอบกลับ
                    }
                },
                timeout=300  # ✅ Increased from 180s to 300s (5 min) for cold boot
            )
            
            if resp.status_code == 200:
                response_text = resp.json().get("response", "").strip()
                # ... (rest of success logic) ...
                
                # ✅ Debug: Check for duplicate blocks
                if '###BLOCK1###' in response_text:
                    block1_count = response_text.count('###BLOCK1###')
                    if block1_count > 1:
                        print(f"   🔍 DEBUG: Found {block1_count} occurrences of BLOCK1 in response")
                
                # ✅ Remove duplicate blocks before parsing (moved logic here for cleaner flow)
                cleaned_response, num_duplicates = remove_duplicate_blocks(response_text)
                if num_duplicates > 0:
                    print(f"   ⚠️ Removed {num_duplicates} duplicate blocks from Typhoon response")

                # Extract translations using regex from cleaned response
                results = [""] * len(texts)
                missing_blocks = []
                failed_validation_indices = []

                for i in range(len(texts)):
                    match = re.search(rf"###BLOCK{i+1}###\s*(.*?)(?=\s*###BLOCK{i+2}###|$)", cleaned_response, re.DOTALL)
                    if match:
                        block_content = match.group(1).strip()
                        # Clean up common prefixes/suffixes from LLM
                        block_content = re.sub(r'^(Here is the translation:|Translation:|Output:)\s*', '', block_content, flags=re.IGNORECASE)
                        block_content = re.sub(r'^\*+|\*+$', '', block_content)
                        results[i] = block_content.strip()

                        # --- Validation v2: Strict Checking ---
                        # Logic: Output should NOT contain scripts from other CJK/Thai languages unless it matches target.
                        if target_lang != "tha_Thai":
                             # Check for LEAKED THAI chars
                             thai_count = sum(1 for c in block_content if '\u0e00' <= c <= '\u0e7f')
                             if thai_count > 0:
                                 print(f"   ⚠️ Block {i+1} validation failed: Found Thai characters in {target_lang} output")
                                 failed_validation_indices.append(i)
                                 missing_blocks.append(i)
                                 continue # Skip other checks
                        
                        if target_lang != "kor_Hang":
                            # Check for LEAKED KOREAN chars
                            kor_count = sum(1 for c in block_content if '\uac00' <= c <= '\ud7af')
                            if kor_count > 0:
                                print(f"   ⚠️ Block {i+1} validation failed: Found Korean characters in {target_lang} output")
                                failed_validation_indices.append(i)
                                missing_blocks.append(i)
                                continue

                        if src_lang != target_lang:
                            content_len = len(block_content)
                            if content_len > 5:
                                # Standard Check: Is it mostly Source Script?
                                bad_count = 0
                                if "tha" in src_lang: bad_count = sum(1 for c in block_content if '\u0e00' <= c <= '\u0e7f')
                                elif "kor" in src_lang: bad_count = sum(1 for c in block_content if '\uac00' <= c <= '\ud7af')
                                elif "jpn" in src_lang: bad_count = sum(1 for c in block_content if '\u3040' <= c <= '\u30ff')
                                
                                # Threshold: 20% (Lowered from 50% to be stricter)
                                if bad_count / content_len > 0.2:
                                    print(f"   ⚠️ Block {i+1} validation failed: Output is still {src_lang} ({bad_count}/{content_len} chars)")
                                    failed_validation_indices.append(i)
                                    missing_blocks.append(i) 

                    else:
                        missing_blocks.append(i)
                
                # ✅ Retry logic: if >30% blocks missing OR validation failed
                # If specifically failed validation, we definitely want to retry
                missing_rate = len(missing_blocks) / len(texts) if texts else 0
                
                if (missing_blocks or failed_validation_indices) and attempt < max_retries:
                    if failed_validation_indices:
                         print(f"   🔄 Retry {attempt + 1}/{max_retries}: Found {len(failed_validation_indices)} blocks not translated (Language Mismatch)")
                         # Optional: Append "Please actually translate this time" to prompt for retry?
                         # For now, simple retry implies re-sampling
                    elif missing_rate > 0.3:
                        print(f"   🔄 Retry {attempt + 1}/{max_retries}: {len(missing_blocks)} blocks missing")
                    
                    continue  # Retry with same prompt
                
                # Fill missing blocks with original text ONLY if result is truly empty
                for i in missing_blocks:
                    if not results[i]:
                        print(f"   ⚠️ Block {i+1} not found (empty), using original text")
                        results[i] = texts[i]
                    else:
                        print(f"   ⚠️ Block {i+1} failed validation (kept imperfect result) instead of reverting")
                
                # Log summary
                if missing_blocks:
                    print(f"   ⚠️ Typhoon: {len(missing_blocks)}/{len(texts)} blocks had issues (missing or failed validation)")
                
                return results

            elif resp.status_code in [500, 503]:
                # ✅ Handle Model Loading Error specifically
                import time
                error_msg = resp.text
                print(f"   ⏳ Server busy/loading ({resp.status_code}): {error_msg}")
                if "loading model" in error_msg.lower() or "busy" in error_msg.lower():
                    wait_time = 20 * (attempt + 1)
                    print(f"   💤 Waiting {wait_time}s for model to load...")
                    time.sleep(wait_time)
                    continue # Retry
                else:
                    print(f"   ❌ API Error: {resp.status_code} - {resp.text}")
            else:
                 print(f"   ❌ API Error: {resp.status_code} - {resp.text}")

        except Exception as e:
            print(f"⚠️ Typhoon error (attempt {attempt + 1}/{max_retries + 1}): {e}")
            if "ReadTimeout" in str(e) or "ConnectTimeout" in str(e):
                 # Timeout usually means model is stuck loading big context or just slow
                 print(f"   💤 Timeout hit. Waiting 10s before retry...")
                 import time
                 time.sleep(10)
            
            if attempt < max_retries:
                print(f"   🔄 Retrying...")
                continue
    
    return [""] * len(texts)
