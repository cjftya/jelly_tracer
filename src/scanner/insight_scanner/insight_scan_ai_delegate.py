import re
import json
from scanner.insight_scanner.insight_scan_prompt_values import InsightScanPromptValues
from ollama_manager import OllamaManager

class InsightScanAIDelegate:
    def __init__(self, ollama_manager: OllamaManager, output_callback):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.chunk_count = [0]

    def execute_double_scan(self, master_brief):
        try:
            # 1. 데이터 다이어트 (L2 증거와 기본 정보만 추출)
            target_data = master_brief.get("analysis_context", {}).get("target_data", {})
            l2_evidence = master_brief.get("deep_dive_evidence", {})
            junior_report = master_brief.get("analysis_context", {}).get("report_data", "No report available.")
            
            # Phase 2를 위한 가벼운 원본 데이터 생성
            compact_original = {
                "target_data": target_data,
                "deep_dive_evidence": l2_evidence
            }

            # --- Phase 1: Zero-Trust Audit ---
            self.output_callback("\n🔍 Phase 1: Auditing L1 Hypothesis against Physical Evidence...")
            
            p1_user_content = f"""
### [Evidence Case File]
- **Junior Investigator's Hypothesis (L1)**: {junior_report}

### [Physical Evidence (L2 - Ground Truth)]
{json.dumps(l2_evidence, separators=(',', ':'))}
"""
            p1_context = [
                {"role": "system", "content": InsightScanPromptValues.getPhase1SystemPrompt()}, 
                {"role": "user", "content": p1_user_content}
            ]

            print(p1_context)
            print("\n\n")

            p1_raw_res = self.ollama_manager.request(
                p1_context, 
                options=self.ollama_manager.getL2Phase1Option(), 
                chunk_callback=self._chunk_callback
            )

            total_tokens = p1_raw_res.get("prompt_eval_count", 0) + p1_raw_res.get("eval_count", 0)
            if self.output_callback:
                self.output_callback(f"\\token {total_tokens}")

            print(p1_raw_res)
            print("\n\n")

            p1_content = self._get_content_from_res(p1_raw_res)
            
            # <think> 로그 출력
            p1_thought = self._extract_thought(p1_content)
            if p1_thought and self.output_callback:
                self.output_callback(f"\n\n🤔 [Phase 1: Forensic Thought]\n{p1_thought}\n")

            # [핵심] Phase 1의 긴 설명 중 'Final Output' 혹은 결론만 추출하여 P2 오염 방지
            p1_pure_audit = self._extract_final_verdict(p1_content)

            if not p1_pure_audit:
                return "❌ Phase 1 Failure: Could not extract valid audit results."

            # --- Phase 2: Audit & Verdict ---
            self.output_callback("\n⚖️ Phase 2: Finalizing Verdict based on Audit Results...")
            
            # Phase 2에는 오직 팩트(L2)와 Phase 1의 최종 결론만 전달
            p2_user_content = f"""
Finalize the report based on the Audit Results.

[Physical Evidence (L2)]
{json.dumps(compact_original, separators=(',', ':'))}

[P1 Audit Results]
{p1_pure_audit}
"""
            p2_context = [
                {"role": "system", "content": InsightScanPromptValues.getPhase2SystemPrompt()},
                {"role": "user", "content": p2_user_content}
            ]

            print(p2_context)
            print("\n\n")
            
            p2_raw_res = self.ollama_manager.request(
                p2_context, 
                options=self.ollama_manager.getL2Phase2Option(), 
                chunk_callback=self._chunk_callback
            )

            total_tokens = p2_raw_res.get("prompt_eval_count", 0) + p2_raw_res.get("eval_count", 0)
            if self.output_callback:
                self.output_callback(f"\\token {total_tokens}")

            print(p2_raw_res)
            print("\n\n")

            p2_content = self._get_content_from_res(p2_raw_res)
            
            # 최종 리포트 추출 (사족 제거)
            final_report = self._strip_thought(p2_content)

            if "[FINAL_INSIGHT]" in final_report:
                return final_report
            else:
                return f"⚠️ Audit Success but Format Missing:\n{final_report}"

        except Exception as e:
            return f"❌ Critical AI Engine Error: {str(e)}"

    def _get_content_from_res(self, res):
        if isinstance(res, dict):
            return res.get('message', {}).get('content', '')
        return str(res)

    def _extract_thought(self, text):
        match = re.search(r"<think>(.*?)(?:</think>|$)", text, re.DOTALL)
        return match.group(1).strip() if match else None

    def _strip_thought(self, text):
        return re.sub(r"<think>.*?(?:</think>|$)", "", text, flags=re.DOTALL).strip()

    def _extract_final_verdict(self, text):
        clean_text = self._strip_thought(text)
        # 'Final Output:' 또는 'Conclusion' 이후의 내용만 찾거나, 없으면 전체 반환
        marker = re.search(r"(?:Final Output|Conclusion|Final Answer):?\s*(.*)", clean_text, re.DOTALL | re.IGNORECASE)
        if marker:
            return marker.group(1).strip()
        return clean_text[-500:].strip() # 마커가 없으면 마지막 500자(결론부)만 취함

    def _chunk_callback(self, chunk):
        spinner_msg = f"\r💬 Thinking... {self.spinner[self.chunk_count[0] % len(self.spinner)]}"
        if self.output_callback:
            self.output_callback(spinner_msg, False)
        self.chunk_count[0] += 1