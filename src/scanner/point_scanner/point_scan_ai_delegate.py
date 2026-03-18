import re
from datetime import datetime
from scanner.point_scanner.point_scan_prompt_values import PointScanPromptValues
from ollama_manager import OllamaManager

class PointScanAIDelegate:
    def __init__(self, ollama_manager: OllamaManager, output_callback):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.history = []
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.chunk_count = [0]
        self.thought_archive = []

    def _extract_load_type(self, cfs_data):
        if not cfs_data or not isinstance(cfs_data, str):
            return "Unknown"
        if "C:Load" in cfs_data: return "Load"
        if "C:ProcLoad" in cfs_data: return "ProcLoad"
        return "Unknown"

    def request_analysis(self, current_round, cfs_block):
        # 1. 라운드별 프롬프트 주입
        if current_round == 1:
            load_type = self._extract_load_type(cfs_block)
            system_instruction = PointScanPromptValues.getSystemPrompt(load_type)
            user_content = (f"Analyze the following FUSION data block according to SOP. "
                            f"Focus on Delta (Slow-Normal). Round 1 Data:\n{cfs_block}")
            self.history = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content}
            ]
        else:
            # 후속 라운드 데이터 주입
            self.history.append({
                "role": "user", 
                "content": f"Round {current_round} Data: {cfs_block}\nIdentify the next suspect or execute 'Backtrack'."
            })

        # 2. Ollama 요청 실행 (스트리밍 지원)
        response = self.ollama_manager.request(
            self.history, 
            think_mode=True,
            chunk_callback=self._chunk_callback
        )

        # 3. 응답 획득 및 토큰 사용량 보고
        raw_result = response["message"]["content"] if isinstance(response, dict) and "message" in response else str(response)

        # 🧪 [증거 보존] 원본 데이터(생각 포함)를 변수에 박제
        self.thought_archive.append({
            "round": current_round,
            "full_content": raw_result,
            "timestamp": datetime.now().isoformat()
        })

        total_used_token = response.get("prompt_eval_count", 0) + response.get("eval_count", 0)
        if self.output_callback:
            self.output_callback(f"\\token {total_used_token}")
        
        # 🛡️ [히스토리 정화] AI의 다음 라운드 지능을 위해 생각 태그만 삭제
        clean_history_content = re.sub(r'<think>.*?</think>', '[Thinking Archived]', raw_result, flags=re.DOTALL)
        self.history.append({"role": "assistant", "content": clean_history_content})
        
        return raw_result

    def parse_slice_request(self, ai_text, is_final_round=False):
        if not ai_text: return None

        # 1. 생각 모드(<think>) 제거 - 모든 판단의 기초
        clean_text = re.sub(r"<think>.*?</think>", "", ai_text, flags=re.DOTALL).strip()

        # 2. 강제 종결(Final Round) 또는 자발적 종결 체크
        # [FINAL_DATA] 태그가 보이거나 8라운드라면 무조건 "Case Closed" 반환
        if is_final_round or "[FINAL_DATA]" in clean_text or "[V]:" in clean_text:
            return "Case Closed"

        # 3. NEXT_TARGET 태그 검색 (수사관님의 기존 로직)
        pattern = r"(?:\[NEXT_TARGET\]|\[NEXT\]|TARGET_SLICE):?\s*(.*)"
        match = re.search(pattern, clean_text, re.IGNORECASE)

        if match:
            # 첫 줄 추출 및 정규화
            raw_line = match.group(1).split('\n')[0].strip()
            target = re.sub(r"^['\"`\[\(]+|['\"`\]\)]+$", "", raw_line).strip()
            target = target.rstrip('.')

            u_target = target.upper()

            # 키워드 기반 종결 확인
            if any(kw in u_target for kw in ["CASE CLOSED", "DONE", "FINISHED", "CONCLUDED"]):
                return "Case Closed"

            # 백트랙 확인
            if "BACKTRACK" in u_target: 
                return "Backtrack"

            # 유효하지 않은 타겟 처리
            if u_target in ['NONE', 'N/A', 'UNKNOWN', '']: 
                return None

            return target

        return None

    def trim_last_cfs_data(self):
        if len(self.history) >= 2:
            # 마지막 Assistant 응답(실패한 추론)과 User 요청(CFS 데이터) 제거
            self.history.pop() 
            self.history.pop()
            if self.output_callback:
                self.output_callback("🛡️ [Token Guard] History trimmed to prevent context overflow.", True)

    def _chunk_callback(self, chunk):
        spinner_msg = f"\r💬 Thinking... {self.spinner[self.chunk_count[0] % len(self.spinner)]}"
        if self.output_callback:
            self.output_callback(spinner_msg, False)
        self.chunk_count[0] += 1