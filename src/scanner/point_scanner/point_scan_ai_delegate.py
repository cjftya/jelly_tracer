import re
from scanner.point_scanner.point_scan_prompt_values import PointScanPromptValues
from ollama_manager import OllamaManager

class PointScanAIDelegate:
    def __init__(self, ollama_manager: OllamaManager, output_callback):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.chunk_count = [0]
        self.thought_archive = []

    def request_analysis(self, context_dict):
        # 1. 컨텍스트 텍스트 구성
        context_text = f"""
            [Investigation Context]
            - Target Thread: {context_dict['thread_name']}
            - Thread IDs: {context_dict['utid_info']}

            [L1 Delta Tree Data]
            {context_dict['tree_data']}
            """
        
        contents = [
            {"role": "system", "content": PointScanPromptValues.getSystemPrompt()},
            {"role": "user", "content": context_text}
        ]

        # 2. Ollama 요청 실행
        response = self.ollama_manager.request(
            contents, 
            options=self.ollama_manager.getL1Option(),
            chunk_callback=self._chunk_callback
        )

        raw_result = response["message"]["content"] if isinstance(response, dict) and "message" in response else str(response)

        # ---------------------------------------------------------
        # 🎯 [핵심] Anchor(닻) 기반 분리 로직
        # ---------------------------------------------------------
        anchor = "[JUDGMENT]"
        if anchor in raw_result:
            # [JUDGMENT] 위치를 찾아 앞부분(생각)과 뒷부분(보고서)을 나눔
            split_pos = raw_result.find(anchor)
            thought_part = raw_result[:split_pos]
            final_report = raw_result[split_pos:].strip()
            
            # 생각 부분에서 태그 찌꺼기 제거 후 아카이브에 저장
            clean_thought = thought_part.replace("<think>", "").replace("</think>", "").strip()
            if clean_thought:
                self.thought_archive.append(clean_thought)
                if self.output_callback:
                    self.output_callback("\n🧠 [AI Reasoning Archive Updated]", True)
        else:
            # 만약 [JUDGMENT] 키워드가 없다면 최후의 수단으로 태그만 제거
            final_report = re.sub(r'<think>.*?</think>', '', raw_result, flags=re.DOTALL).strip()
            if not final_report:
                final_report = raw_result # 파싱 실패 시 원본이라도 반환

        # 3. 토큰 사용량 출력
        total_tokens = response.get("prompt_eval_count", 0) + response.get("eval_count", 0)
        if self.output_callback:
            self.output_callback(f"\\token {total_tokens}")

        return final_report

    def _chunk_callback(self, chunk):
        spinner_msg = f"\r💬 Thinking... {self.spinner[self.chunk_count[0] % len(self.spinner)]}"
        if self.output_callback:
            # False 인자를 주어 한 줄에서 갱신되도록 처리 (UI 구현에 따라 다름)
            self.output_callback(spinner_msg, False)
        self.chunk_count[0] += 1