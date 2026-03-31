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
            
            thought_match = re.search(r"\[\[THOUGHT\]\](.*?)\[\[/THOUGHT\]\]", full_content, re.DOTALL)
            if thought_match:
                thinking_process = thought_match.group(1).strip()
                final_analysis = re.sub(r"\[\[THOUGHT\]\].*?\[\[/THOUGHT\]\]", "", full_content, flags=re.DOTALL).strip()
            else:
                if "[[THOUGHT]]" in full_content:
                    parts = full_content.split("[[THOUGHT]]")
                    thinking_process = parts[1].split("\n\n")[0].strip() # 대략 첫 단락만 추출
                    final_analysis = full_content.replace("[[THOUGHT]]", "").strip()
                else:
                    thinking_process = "Internal reasoning was not tagged correctly by AI."
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