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

            print(f"Phase1: {p1_raw_res}")

            p1_content = self._get_content_from_res(p1_raw_res)
            
            # 리즈닝 과정(Think) 추출 및 출력 (수사관용 참고 데이터)
            p1_thought = self._extract_thought(p1_content)
            if p1_thought and self.output_callback:
                self.output_callback(f"\n\n🤔 [Forensic Reasoning Log]\n{p1_thought}\n")

            # 기술적 팩트 시트 본문만 추출 (사족 제거)
            technical_fact_sheet = self._strip_thought(p1_content)

            # 1. 더 유연한 정규표현식 패턴 (별표, 콜론, 공백 등 대응)
            pattern = r"SliceId\D+(\d+)" 
            match = re.search(pattern, p1_content, re.IGNORECASE)

            if match:
                # 패턴 매칭 성공: 숫자 그룹 추출
                target_id = match.group(1) 
            else:
                # 패턴 매칭 실패 시: 
                # p1_content는 문자열이므로 .get() 대신 안전한 기본값(None)을 할당합니다.
                self.output_callback("⚠️ [Warning] AI report did not contain a valid SliceId.")
                target_id = None

            self.output_callback("\n✍️ [Phase 2] Drafting Executive Summary...")
            
            for_report = master_brief.get("for_report", {})
            p2_system_prompt = InsightScanPromptValues.getPhase2SystemPrompt()
            p2_user_content = f"### [Technical Fact Sheet (Source)]\n{technical_fact_sheet}\n\n### [Forensic Data]\n{for_report}"
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

            print(f"Phase2: {p2_raw_res}")

            p2_content = self._get_content_from_res(p2_raw_res)
            
            # 최종 리포트 반환
            final_reports = [self._strip_thought(p2_content), self.find_node_by_id(l2_evidence, target_id)]

            return final_reports

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

    def find_node_by_id(self, data_source, target_id):
        # 1. 입력 데이터가 리스트인 경우 (Flat Candidates 리스트 처리)
        if isinstance(data_source, list):
            for node in data_source:
                if node.get('slice_id') == target_id:
                    return node
            return None

        # 2. 입력 데이터가 딕셔너리인 경우 (Tree 구조 또는 단일 노드 처리)
        if isinstance(data_source, dict):
            # 현재 노드가 타겟인지 확인
            if data_source.get('slice_id') == target_id:
                return data_source
            
            # 'candidates' 키가 있는 경우 (플랫 모드 패키지 형태)
            if 'candidates' in data_source:
                return self.find_node_by_id(data_source['candidates'], target_id)
            
            # 'children' 키가 있는 경우 (트리 모드 재귀 탐색)
            for child in data_source.get('children', []):
                result = self.find_node_by_id(child, target_id)
                if result:
                    return result

        return None