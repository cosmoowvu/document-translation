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
        
        # Llama 3.2 refine prompt - Clear and Direct
        prompt = (
            f"You are refining {target_name} text from NLLB machine translation.\n\n"
            f"CRITICAL RULES:\n"
            f"1. Input is ALREADY in {target_name} - DO NOT translate to English!\n"
            f"2. Output MUST stay in {target_name} - same language as input\n"
            f"3. Make the text more natural and fluent\n"
            f"4. Fix awkward phrasing and improve word choices\n"
            f"5. Keep the exact meaning - no additions or removals\n\n"
            f"FORBIDDEN:\n"
            f"- Translating to any other language\n"
            f"- Changing the language\n"
            f"- Adding explanations\n\n"
            f"Input ({target_name} from NLLB):\n"
            f"{combined_text}\n\n"
            f"Output (improved {target_name} with ###BLOCKn### markers):"
        )
        
        print(f"   ✨ Refining with Llama 3.2 ({len(texts)} blocks)...")
        
        try:
            resp = requests.post(
                self.url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.5, "num_predict": 4096}
                },
                timeout=120
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
