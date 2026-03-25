import re
import json
from scanner.point_scanner.point_scan_prompt_values import PointScanPromptValues
from ollama_manager import OllamaManager

class PointScanAIDelegate:
    def __init__(self, ollama_manager: OllamaManager, output_callback):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.chunk_count = [0]
        self.thought_archive = [] # AI의 깊은 생각 과정을 저장

    def request_analysis(self, context_dict):
        # 1. 입력 컨텍스트 구성
        context_text = (
f"[Investigation Context]\n"
f"- Target Thread: {context_dict['thread_name']}\n"
f"- Thread Metadata: {context_dict['utid_info']}\n\n"
f"[Condensed Performance JSON Tree]\n"
f"{context_dict['tree_data']}\n\n"
f"Based on the data above, execute the defined 'Analysis Logic' and select the single optimization target."
        )
        
        contents = [
            {"role": "system", "content": PointScanPromptValues.getSystemPrompt()},
            {"role": "user", "content": context_text}
        ]

        # 2. Ollama 요청 (R1 모델의 추론 특성 반영)
        response = self.ollama_manager.request(
            context=contents, 
            options=self.ollama_manager.getL1Option(),
            chunk_callback=self._chunk_callback
        )

        raw_result = response["message"]["content"] if isinstance(response, dict) and "message" in response else str(response)

        # ---------------------------------------------------------
        # 🎯 [핵심] 새 프롬프트의 Output Format에 맞춘 파싱 앵커
        # ---------------------------------------------------------
        anchor = "**[Selected Slice]**" # 프롬프트에 정의된 첫 번째 섹션 헤더
        
        if anchor in raw_result:
            # 앵커를 기준으로 앞부분은 AI의 생각(<think>), 뒷부분은 최종 보고서
            split_pos = raw_result.find(anchor)
            thought_part = raw_result[:split_pos]
            final_report = raw_result[split_pos:].strip()

            # 생각 부분에서 태그 제거 후 저장
            clean_thought = re.sub(r'</?think>', '', thought_part).strip()
            if clean_thought:
                self.thought_archive.append(clean_thought)
                if self.output_callback:
                    self.output_callback("\n🧠 [AI Reasoning Archived: Internal Logic Analysis Executed]", True)
        else:
            # 앵커가 없으면 최소한 <think> 태그라도 제거
            final_report = re.sub(r'<think>.*?</think>', '', raw_result, flags=re.DOTALL).strip()
            if not final_report:
                final_report = raw_result

        # 3. 사용량 및 토큰 정보 출력
        total_tokens = response.get("prompt_eval_count", 0) + response.get("eval_count", 0)
        if self.output_callback:
            self.output_callback(f"\\token {total_tokens}")

        return final_report

    def _chunk_callback(self, chunk):
        spinner_msg = f"\r💬 Thinking... {self.spinner[self.chunk_count[0] % len(self.spinner)]}"
        if self.output_callback:
            self.output_callback(spinner_msg, False)
        self.chunk_count[0] += 1

    def test_request(self):
        contents = [
            {"role": "user", "content": "Why is the UI slow? in android xml, better compose?"}
        ]
        response = self.ollama_manager.request(
            contents=contents, 
            options=self.ollama_manager.getL1Option(),
            chunk_callback=self._chunk_callback
        )
        print(response)
