import re
import json
from scanner.insight_scanner.insight_scan_prompt_values import InsightScanPromptValues
from llm_requester import LLMRequester

class InsightScanAIDelegate:
    def __init__(self, llm_requester: LLMRequester, output_callback):
        self.output_callback = output_callback
        self.llm_requester = llm_requester

    def request_analysis(self, context, fact_only=False):
        try:
            system_prompt = InsightScanPromptValues.getSystemPrompt(fact_only)
            string_context = json.dumps(context, indent=2, ensure_ascii=False)
            ai_context = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": string_context}
            ]

            raw_res = self.llm_requester.request(
                context=ai_context,
                options=self.llm_requester.getInsightScanOption(),
                chunk_callback=lambda chunk: self.llm_requester.chunk_callback(chunk, self.output_callback)
            )
            total_tokens = raw_res.get("prompt_eval_count", 0) + raw_res.get("eval_count", 0)
            if self.output_callback:
                self.output_callback(f"\\token {total_tokens}")

            full_content = raw_res.get("message", {}).get("content", "")
            
            match = re.search(r"Executive\s+Summary", full_content, re.IGNORECASE)
            if match:
                word_start = match.start()
                line_start = full_content.rfind('\n', 0, word_start) + 1
                thinking_process_raw = full_content[:line_start].strip()
                final_analysis = full_content[line_start:].strip()
                thinking_process = re.sub(r"\[{1,2}/?THOUGHT\]{1,2}", "", thinking_process_raw, flags=re.IGNORECASE).strip()
                if not thinking_process:
                    thinking_process = "Internal reasoning was processed."
            else:
                thinking_process = "Anchor text 'Executive Summary' not found."
                final_analysis = full_content.strip()

            target_pattern = re.compile(r'Target-?ID[:\s]+(\d+)', re.IGNORECASE)
            target_match = target_pattern.search(final_analysis)
            target_id = target_match.group(1) if target_match else 0

            # 결과 재구성
            processed_res = {
                "thinking": thinking_process, 
                "analysis": final_analysis,   
                "target_id": target_id,
                "raw": raw_res         
            }

            return processed_res

        except Exception as e:
            return {"error": f"❌ Critical AI Engine Error: {str(e)}"}