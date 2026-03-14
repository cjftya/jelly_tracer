import re

from src.prompt_values import PromptValues
from ollama_manager import OllamaManager

class FusionAIDelegate:
    def __init__(self, ollama_manager: OllamaManager, output_callback):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.history = []
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.chunk_count = [0]

    def _extract_load_type(self, cfs_data):
        if "C:Load" in cfs_data:
            return "Load"
        elif "C:ProcLoad" in cfs_data:
            return "ProcLoad"
        else:
            return "Unknown"

    def request_final_report(self, sched_md, profile_md, raw_ai_verdict):
        design_prompt = "앞서 수립된 디자인 원칙에 따라 아래 데이터를 전문가용 리포트로 재구성해줘."
        report_context = [
            {"role": "system", "content": PromptValues.getReportDesignerPrompt()},
            {"role": "user", "content": f"""
                {design_prompt}
                
                [DATA - Scheduling]
                {sched_md}
                
                [DATA - Profiling]
                {profile_md}
                
                [RAW VERDICT]
                {raw_ai_verdict}
            """}
        ]
        pretty_report = self.ollama_manager.request(report_context)
        result = pretty_report["message"]["content"] if isinstance(pretty_report, dict) and "message" in pretty_report else str(pretty_report)
        return result

    def request_analysis(self, current_round, cfs_block):
        if current_round == 1:
            user_content = (f"Analyze the following FUSION data block according to SOP. "
                f"Provide a CRP verdict or request a TARGET_SLICE.\n\n"
                f"Round 1 Data: {cfs_block}")
            load_type = self._extract_load_type(cfs_block)
            # 첫 라운드: 시스템 지침 + 첫 데이터로 히스토리 초기화
            self.history = [
                {"role": "system", "content": PromptValues.getFusionCoreSystemPrompt(load_type)},
                {"role": "user", "content": user_content}
            ]
        else:
            # 이후 라운드: 이전 기록 뒤에 새로운 데이터만 추가
            self.history.append({"role": "user", "content": f"Round {current_round} Data: {cfs_block}"})

        # 누적된 히스토리 전체를 전달 (메모리 유지)
        response = self.ollama_manager.request(
            self.history, chunk_callback=self._chunk_callback
        )
        
        # AI의 답변도 히스토리에 저장 (이래야 다음 라운드에서 자기 말을 기억함)
        result = response["message"]["content"] if isinstance(response, dict) and "message" in response else str(response)
        self.history.append({"role": "assistant", "content": result})
        
        return result

    def parse_slice_request(self, ai_text):
        # AI가 "TARGET_SLICE: [이름]" 형식을 쓰도록 유도하거나 정규식으로 추출
        match = re.search(r"TARGET_SLICE:\s*\[?(\w+)\]?", ai_text)
        return match.group(1) if match else None

    def _chunk_callback(self, chunk):
        spinner_msg = f"\r💬 추론 중... {self.spinner[self.chunk_count[0] % len(self.spinner)]}"
        if self.output_callback:
            self.output_callback(spinner_msg, False)
        else:
            print(spinner_msg, end="", flush=True)
        self.chunk_count[0] += 1