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
            # 수사관님이 정교하게 깎아놓은 컬링 JSON (L2 Evidence)
            l2_evidence = master_brief.get("deep_dive_evidence", {})
            
            self.output_callback("\n🧠 [Phase 1] Analyzing Root Causes...")
            
            p1_system_prompt = InsightScanPromptValues.getPhase1SystemPrompt()
            p1_user_content = f"### [Culled Evidence Tree (JSON)]\n{json.dumps(l2_evidence, indent=2)}"
            p1_context = [
                {"role": "system", "content": p1_system_prompt}, 
                {"role": "user", "content": p1_user_content}
            ]

            p1_raw_res = self.ollama_manager.request(
                context=p1_context, 
                options=self.ollama_manager.getL2Phase1Option(), 
                chunk_callback=self._chunk_callback
            )

            print(p1_raw_res)

            p1_content = self._get_content_from_res(p1_raw_res)
            
            # 리즈닝 과정(Think) 추출 및 출력 (수사관용 참고 데이터)
            p1_thought = self._extract_thought(p1_content)
            if p1_thought and self.output_callback:
                self.output_callback(f"\n\n🤔 [Forensic Reasoning Log]\n{p1_thought}\n")

            # 기술적 팩트 시트 본문만 추출 (사족 제거)
            technical_fact_sheet = self._strip_thought(p1_content)

            self.output_callback("\n✍️ [Phase 2] Drafting Executive Summary...")
            
            p2_system_prompt = InsightScanPromptValues.getPhase2SystemPrompt()
            p2_user_content = f"### [Technical Fact Sheet (Source)]\n{technical_fact_sheet}"
            p2_context = [
                {"role": "system", "content": p2_system_prompt},
                {"role": "user", "content": p2_user_content}
            ]
            
            p2_raw_res = self.ollama_manager.request(
                context=p2_context, 
                model=self.ollama_manager.get_report_only_model(),
                options=self.ollama_manager.getL2Phase2Option(), 
                chunk_callback=self._chunk_callback
            )

            print(p2_raw_res)

            p2_content = self._get_content_from_res(p2_raw_res)
            
            # 최종 리포트 반환
            final_report = self._strip_thought(p2_content)

            return final_report

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

    def _chunk_callback(self, chunk):
        spinner_msg = f"\r💬 Thinking... {self.spinner[self.chunk_count[0] % len(self.spinner)]}"
        if self.output_callback:
            self.output_callback(spinner_msg, False)
        self.chunk_count[0] += 1