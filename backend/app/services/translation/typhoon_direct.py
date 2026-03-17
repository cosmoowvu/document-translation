"""
Typhoon Direct Translation Module
Handles direct translation using Typhoon Translate 1.5 (4B)
Optimized for Thai ↔ English translation
"""
import time
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
        "kor_Hang": "Korean",
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
    
    # Specialized instruction for specific languages
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
    elif "jpn" in target_lang.lower() or "japanese" in target_name.lower():
        extra_instruction = (
            "5. For Japanese, you MUST use ONLY natural Japanese script (Hiragana/Katakana/Kanji).\n"
            "   - DO NOT output large spaced out letters or symbols (e.g., 卜 Ｐ Ｉ や ロ ロ ク...).\n"
            "   - Sentences must flow naturally without random spaces separating every character.\n"
        )
        # One-shot example for Japanese
        example_section = (
            "Example:\n"
            "Input:\n###BLOCK1### The table shows data\n"
            "Output:\n###BLOCK1### 表はデータを示しています。\n\n"
        )

    # Typhoon Translate prompt
    prompt = (
        f"Translate each block below from {lang_names.get(src_lang, src_lang)} into {target_name}.\n"
        "Produce fluent, natural translations that preserve the original meaning and tone.\n\n"
        "CRITICAL RULES:\n"
        f"1. You MUST output exactly {num_blocks} blocks with markers ###BLOCK1### to ###BLOCK{num_blocks}###\n"
        "2. Translate each block SEPARATELY - do NOT merge blocks together\n"
        "3. Each block's translation must appear after its ###BLOCKn### marker\n"
        "4. Output ONLY the translated text. NO notes, NO explanations, NO commentary, NO self-evaluation.\n"
        "   - Stop immediately after the last translated word. Do not write anything else.\n"
        f"{extra_instruction}"
        "6. Translate ALL text naturally, transcribing proper names phonetically where needed.\n\n"
        f"{example_section}"
        f"Input ({num_blocks} blocks):\n{combined_text}\n\n"
        f"Output ({num_blocks} blocks in {target_name}):"
    )


    
    print(f"   📤 Sending Batch Prompt (Typhoon - {len(texts)} blocks)...")
    
    # ✅ Check cancelled flag before translation
    if job_status and job_id and job_status.get(job_id, {}).get("cancelled", False):
        print("   🚫 Job cancelled - stopping Typhoon translation")
        return [""] * len(texts), list(range(len(texts)))
    
    max_retries = 2  # Increased retries for robustness
    
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                ollama_url,
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.4,  # Increased slightly to avoid repetitive loops
                        "repeat_penalty": 1.25, # Increased penalty to discourage repetition
                        "num_predict": 4096,  
                        "top_p": 0.9          
                    }
                },
                timeout=300
            )
            
            if resp.status_code == 200:
                response_text = resp.json().get("response", "").strip()
                
                # ... [Keep existing deduplication logic] ...
                if '###BLOCK1###' in response_text:
                    block1_count = response_text.count('###BLOCK1###')
                    if block1_count > 1:
                        print(f"   🔍 DEBUG: Found {block1_count} occurrences of BLOCK1 in response")
                
                cleaned_response, num_duplicates = remove_duplicate_blocks(response_text)
                if num_duplicates > 0:
                    print(f"   ⚠️ Removed {num_duplicates} duplicate blocks from Typhoon response")

                results = [""] * len(texts)
                missing_blocks = []

                for i in range(len(texts)):
                    match = re.search(rf"###BLOCK{i+1}###\s*(.*?)(?=\s*###BLOCK{i+2}###|$)", cleaned_response, re.DOTALL)
                    if match:
                        block_content = match.group(1).strip()
                        # Strip common LLM prefixes
                        block_content = re.sub(r'^(Here is the translation:|Translation:|Output:|Translated text:)\s*', '', block_content, flags=re.IGNORECASE)
                        block_content = re.sub(r'^\*+|\*+$', '', block_content)
                        
                        # [NEW] Strip trailing NOTE/COMMENTARY that the model adds after the translation
                        # Catches:
                        #   "Note: ...", "The translation adheres...", "This is a...", etc.
                        #   Also catches bullet-list self-evaluation the model sometimes echoes from the prompt
                        block_content = re.sub(
                            r'\s*\n+\s*(?:[-*]\s+|)(Note[:\s]|Translation(?:\s+[Nn]ote)?[:\s]|The translation|In (this|the) (context|story|text)|This is a |If you |For (educational|context)|Survival |Building|Such |Without |Free-|For real|Regard|The Thai|Meaning and intent|The output is|Tone \(|No extra|Translat(?:ion|or) note)[\s\S]*$',
                            '', block_content, flags=re.IGNORECASE
                        ).strip()

                        # [NEW] Aggressive Hallucination Check for Repetitive Patterns
                        # Detect "เก้าเก้าเก้า..." or "aaaaa..."
                        # Pattern: (any 2+ chars) repeated 5+ times consecutively
                        repeat_match = re.search(r'(.{2,})\1{4,}', block_content)
                        if repeat_match:
                            print(f"   🚨 Block {i+1} repetitive hallucination detected: '{repeat_match.group(1)}'...")
                            # Truncate at the start of the repetition
                            block_content = block_content[:repeat_match.start()].strip()
                            print(f"      ✂️ Truncated repetition")

                        # Safety check: Detect hallucination (output way longer than input)
                        src_len = len(texts[i])
                        result_len = len(block_content)
                        
                        # If result is >10x longer than input, likely hallucination - truncate
                        if result_len > src_len * 10 and result_len > 500:
                            print(f"   🚨 Block {i+1} hallucination detected: {result_len} chars (input: {src_len})")
                            max_len = src_len * 3
                            block_content = block_content[:max_len]
                            last_period = block_content.rfind('。')
                            if last_period == -1:
                                last_period = block_content.rfind('.')
                            if last_period > max_len // 2:
                                block_content = block_content[:last_period + 1]
                            print(f"      ✂️ Truncated to {len(block_content)} chars")

                        # NO VALIDATION - just accept the result
                        results[i] = block_content
                        
                    else:
                        missing_blocks.append(i)
                
                # Retry only if many blocks are missing (parsing issue)
                missing_rate = len(missing_blocks) / len(texts) if texts else 0
                
                if missing_rate > 0.5 and attempt < max_retries:
                    print(f"   🔄 Retry {attempt + 1}/{max_retries}: {len(missing_blocks)} blocks missing")
                    continue  # Retry with same prompt
                
                # Fill missing blocks with original text
                for i in missing_blocks:
                    if not results[i]:
                        print(f"   ⚠️ Block {i+1} not found, using original text")
                        results[i] = texts[i]
                
                # Log summary
                if missing_blocks:
                    print(f"   ⚠️ Typhoon: {len(missing_blocks)}/{len(texts)} blocks used original text")
                
                # Return results AND list of failed indices for fallback logic
                # We return ALL missing_blocks (including those kept as imperfect) so Orchestrator can fallback if desired
                return results, missing_blocks
            
            elif resp.status_code in [500, 503]:
                # Handle Model Loading Error specifically
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
                 time.sleep(10)
            
            if attempt < max_retries:
                print(f"   🔄 Retrying...")
                continue
    
    return [""] * len(texts), list(range(len(texts)))
