import re
from prompt_values import PromptValues
from ollama_manager import OllamaManager

class FusionAIDelegate:
    def __init__(self, ollama_manager: OllamaManager, output_callback):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.history = []
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.chunk_count = [0]

    def _extract_load_type(self, cfs_data):
        if not cfs_data or not isinstance(cfs_data, str):
            return "Unknown"
        if "C:Load" in cfs_data: return "Load"
        if "C:ProcLoad" in cfs_data: return "ProcLoad"
        return "Unknown"

    def request_analysis(self, current_round, cfs_block):
        # Round 1: 시스템 프롬프트 및 초기 지침 주입
        if current_round == 1:
            load_type = self._extract_load_type(cfs_block)
            system_instruction = PromptValues.getFusionCoreSystemPrompt(load_type)
            user_content = (f"Analyze the following FUSION data block according to SOP. "
                            f"Focus on Delta (Slow-Normal). Round 1 Data:\n{cfs_block}")
            self.history = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content}
            ]
        else:
            # 후속 라운드: 데이터 추가 및 다음 타겟 요청
            self.history.append({
                "role": "user", 
                "content": f"Round {current_round} Data: {cfs_block}\nIdentify the next suspect or execute 'Backtrack'."
            })

        # Ollama 요청 실행
        response = self.ollama_manager.request(
            self.history, 
            chunk_callback=self._chunk_callback
        )

        # 토큰 사용량 체크 (Ollama 기준)
        total_used_token = response.get("prompt_eval_count", 0) + response.get(
            "eval_count", 0
        )
        self.output_callback("\\token " + str(total_used_token))
        
        # 응답 처리
        raw_result = response["message"]["content"] if isinstance(response, dict) and "message" in response else str(response)
        result = raw_result.strip()
        
        # 히스토리 누적
        self.history.append({"role": "assistant", "content": result})
        return result

    def parse_slice_request(self, ai_text):
        if not ai_text: return None

        # 1. 태그 패턴 최적화: [NEXT_TARGET], [NEXT], TARGET_SLICE 모두 대응
        # 핵심은 'NEXT_TARGET'을 가장 먼저 체크하는 것입니다.
        pattern = r"(?:\[NEXT_TARGET\]|\[NEXT\]|TARGET_SLICE):?\s*\[?([\w\.\$<> /:#-]+)\]?"
        match = re.search(pattern, ai_text, re.IGNORECASE)
        
        if match:
            target = match.group(1).strip()
            
            # 2. 마침표나 사족 제거 (AI가 가끔 'Choreographer.' 처럼 마침표를 찍음)
            target = target.rstrip('.')
            
            # 3. 엔진 예약 키워드 동기화
            u_target = target.upper()
            
            # "Case Closed" 판정 (DONE, FINISHED 등 유연하게 대응)
            if any(kw in u_target for kw in ["CASE CLOSED", "DONE", "FINISHED", "CONCLUDED"]):
                return "Backtrack" if "BACKTRACK" in u_target else "Case Closed"
            
            if "BACKTRACK" in u_target: 
                return "Backtrack"
                
            if u_target in ['NONE', 'N/A', 'UNKNOWN']: 
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
        spinner_msg = f"\r💬 추론 중... {self.spinner[self.chunk_count[0] % len(self.spinner)]}"
        if self.output_callback:
            self.output_callback(spinner_msg, False)
        self.chunk_count[0] += 1