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
        self.candidate_leads = []
        self.investigation_notes = [] # 👈 가설 파괴(의구심) 저장소 추가

    def _extract_load_type(self, cfs_data):
        if not cfs_data or not isinstance(cfs_data, str):
            return "Unknown"
        if "C:Load" in cfs_data: return "Load"
        if "C:ProcLoad" in cfs_data: return "ProcLoad"
        return "Unknown"

    def request_analysis(self, current_round, cfs_block):
        # 1. 수사 스냅샷 및 가이드라인 구성
        snapshot_context = ""
        if self.candidate_leads:
            recent_flow = ""
            # 최근 3회분의 수사 흐름(후보군 및 반박 노트)을 추출하여 단기 기억 보강
            for i, (leads, note) in enumerate(zip(self.candidate_leads[-3:], self.investigation_notes[-3:])):
                recent_flow += f"  - Step {i+1}: {leads}\n"
                recent_flow += f"    [Refutation Note]: {note}\n"
            
            snapshot_context = f"\n[RECENT INVESTIGATION FLOW & DOUBTS]:\n{recent_flow}"

        # 매 라운드 반복 주입할 핵심 제약 사항 (7B 모델의 지시 망각 방지)
        mandatory_reminder = (
            f"\n\n[MANDATORY RULE: ROUND {current_round}/5]\n"
            f"{snapshot_context}"
            "- Perform 'Hypothesis Breaker' inside <think> using the 'Refutation:' keyword.\n"
            "- Start your final answer with [NEXT_TARGET] after </think>."
        )

        # 라운드에 따른 히스토리 초기화 및 업데이트
        if current_round == 1:
            # 1라운드: 시스템 프롬프트 및 초기 분석 지침 설정
            load_type = self._extract_load_type(cfs_block)
            system_instruction = PointScanPromptValues.getSystemPrompt(load_type)
            user_content = (
                f"Analyze the FUSION data. Identify Top-3 potential suspect slices.\n"
                f"Your goal is not to conclude, but to narrow down the search space.\n"
                f"Data:\n{cfs_block}"
            )
            user_content += mandatory_reminder
            self.history = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content}
            ]
        else:
            # 2라운드 이후: 새로운 증거 추가 및 이전 사고(Think) 배제 유도
            user_content = f"[Round {current_round}] New Evidence:\n{cfs_block}" + mandatory_reminder
            self.history.append({"role": "user", "content": user_content})

        # 2. AI 분석 실행 (Ollama API 호출)
        response = self.ollama_manager.request(
            self.history, 
            options=self.ollama_manager.getL1Option(),
            chunk_callback=self._chunk_callback
        )

        raw_result = response["message"]["content"] if isinstance(response, dict) and "message" in response else str(response)

        # 3. 결과 파싱 및 수사 단서 추출
        think_match = re.search(r'<think>(.*?)</think>', raw_result, flags=re.DOTALL)
        thought_content = think_match.group(1).strip() if think_match else ""

        # 토큰 사용량 모니터링 출력
        total_used_token = response.get("prompt_eval_count", 0) + response.get("eval_count", 0)
        if self.output_callback:
            self.output_callback(f"\\token {total_used_token}")

        # [Hypothesis Breaker] 'Refutation:' 키워드를 기반으로 AI의 자기 반박 내용 추출
        ref_match = re.search(r"Refutation\s*[:：]?\s*(.*?)(?:\n|\.|$)", thought_content, re.IGNORECASE)
        if ref_match:
            refutation_note = ref_match.group(1).strip()
        else:
            # 키워드 미검출 시 생각 모드 마지막 부분을 요약본으로 사용
            refutation_note = thought_content[-100:].replace('\n', ' ') if thought_content else "No doubts recorded."
        
        self.investigation_notes.append(refutation_note)

        # [CANDIDATES] 태그에서 현재 라운드의 용의자 리스트 추출 및 저장
        cand_match = re.search(r"\[CANDIDATES\]:?\s*(.*)", raw_result, re.IGNORECASE)
        if cand_match:
            current_cands = cand_match.group(1).split('\n')[0].strip()
            self.candidate_leads.append(current_cands)

        # 4. 데이터 아카이브 및 컨텍스트 정화
        # 생각 과정 원본은 L2 분석 및 사후 검토를 위해 별도 저장
        self.thought_archive.append({
            "round": current_round,
            "thought": thought_content,
            "full_content": raw_result,
            "timestamp": datetime.now().isoformat()
        })
        
        # [Context Optimization] 7B 모델의 메모리 과부하 방지를 위해 <think>를 요약 문구로 치환
        clean_content = re.sub(r'<think>.*?</think>', f'\n> [Strategic Thinking Archived for Round {current_round}]\n', raw_result, flags=re.DOTALL)
        self.history.append({"role": "assistant", "content": clean_content})
        
        return raw_result

    def parse_slice_request(self, ai_text, is_final_round=False):
        if not ai_text: return None

        # 1. 생각 모드(<think>) 제거 - 모든 판단의 기초
        clean_text = re.sub(r"<think>.*?</think>", "", ai_text, flags=re.DOTALL).strip()

        # 2. 강제 종결(Final Round) 또는 자발적 종결 체크
        # [FINAL_DATA] 태그가 보이거나 8라운드라면 무조건 "Case Closed" 반환
        if is_final_round or "[FINAL_DATA]" in clean_text or "[V]:" in clean_text:
            return "Case Closed"

        # 3. NEXT_TARGET 태그 검색
        pattern = r"(?:\[?NEXT_TARGET\]?|\[?NEXT\]?|TARGET_SLICE|Next Target):?\s*(.*)"
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