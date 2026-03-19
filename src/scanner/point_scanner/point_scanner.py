import re
from datetime import datetime
from scanner.point_scanner.point_scan_data_delegate import PointScanDataDelegate
from scanner.point_scanner.point_scan_ai_delegate import PointScanAIDelegate
from scanner.base_scanner import BaseScanner

class PointScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        self.max_round = 5
        self.backtrack_limit = 2  # 💡 백트랙 최대 허용 횟수
        self.backtrack_count = 0  # 💡 현재 백트랙 누적 횟수
        self.target_package = None
        
        # Delegates
        self.data_provider = None
        self.ai_analyst = None
        
        # State
        self.utid_n = None
        self.utid_s = None
        self.investigated_scopes = [] 
        self.target_thread = None
        self.scope_stack = [] 

    def start(self, ollama_manager, output_callback):
        super().start(ollama_manager, output_callback)
        self.data_provider = PointScanDataDelegate(output_callback)
        self.ai_analyst = PointScanAIDelegate(ollama_manager, output_callback)

    def run(self, trace_normal, trace_slow, target_package, analysis_data=None):
        super().run(trace_normal, trace_slow, target_package, analysis_data)
        self.target_package = target_package
        self.data_provider.init(trace_normal, trace_slow, target_package)
        self.output_callback(f"🚀 [Point-Scan] Investigation Started: {target_package}")
        
        # ---------------------------------------------------------
        # 1. 수사 대상 확정 (Targeting & Identification)
        # ---------------------------------------------------------
        self.utid_n, self.utid_s, self.target_thread = self.data_provider.identify_targets()
        if not self.target_thread:
            self.output_callback("❌ Fail: Could not identify target threads.", True)
            return
            
        # 수사 고유 ID 생성 (추적성 확보)
        investigation_id = f"FC-{datetime.now().strftime('%m%d-%H%M')}"
        self.output_callback(f"🎯 [Target Locked] Thread: {self.target_thread} | ID: {investigation_id}", True)

        # ---------------------------------------------------------
        # 2. 초기 정찰 (Initial Reconnaissance)
        # ---------------------------------------------------------
        # 가장 지연이 심한 '피봇(Pivot)' 슬라이스를 찾아 수사 범위(Scope)를 압축
        pivot = self.data_provider.find_worst_slice(self.utid_n, self.utid_s)

        ts_s, ts_n = None, None
        if pivot:
            ts_s = self.data_provider.get_slice_bounds("slow", self.utid_s, pivot)

        # [Safety Check] 피봇 좌표 조회 실패 시 전체 범위(Global)로 자동 전환
        if ts_s:
            ts_n = self.data_provider.get_sync_bounds("normal", ts_s)
            self.output_callback(f"🎯 [Focus Mode] Investigating '{pivot}' window.", True)
        else:
            ts_s = self.data_provider.get_global_bounds("slow")
            ts_n = self.data_provider.get_sync_bounds("normal", ts_s)
            self.output_callback("🌐 [Global Mode] No specific pivot found. Analyzing full trace.", True)

        # 수사 이력 관리를 위한 스코프 스택 초기화
        self.scope_stack.append((ts_n, ts_s)) 
        cfs_block = self.data_provider.generate_cfs(self.utid_n, ts_n, self.utid_s, ts_s)
        
        # ---------------------------------------------------------
        # 3. AI 협업 순환 분석 (Iterative AI Analysis)
        # ---------------------------------------------------------
        current_round = 1
        while current_round <= self.max_round:
            is_final_round = (current_round == self.max_round)
            self.output_callback(f"\n📡 [Round {current_round}/{self.max_round}] Analyzing...")

            # 최종 라운드일 경우 강제 종결 지침(Mandate) 주입
            current_cfs = cfs_block
            if is_final_round:
                current_cfs += (
                    f"\n\n🚨 [SYSTEM MANDATE: FINAL ROUND {current_round}/{self.max_round}] 🚨\n"
                    "You MUST conclude the investigation NOW.\n"
                    "Output [FINAL_DATA] tags (V, O, C, A, S, T) based on evidence."
                )
            
            # AI 분석 요청 및 결과 파싱
            ai_response = self.ai_analyst.request_analysis(current_round, current_cfs)
            target_slice = self.ai_analyst.parse_slice_request(ai_response)
            
            # 사고 과정(<think>) 추출 및 UI 피드백
            thought_process = "Analyzing..."
            think_match = re.search(r"<think>(.*?)</think>", ai_response, re.S)
            reasoning_match = re.search(r"\[REASONING\]:(.*?)(?=\[|$)", ai_response, re.S)

            if think_match:
                thought_process = think_match.group(1).strip()
            elif reasoning_match:
                thought_process = reasoning_match.group(1).strip()

            self.output_callback(f"🤖 [Thinking] {thought_process}")

            # [CASE A: 수사 종결] 자발적 종료 혹은 최대 라운드 도달
            if not target_slice or "Case Closed" in target_slice or is_final_round:
                if is_final_round:
                    self.output_callback("⚠️ [Hard-Stop] Max rounds reached. Synthesizing data...", True)

                # 최종 증거 데이터 및 부가 메타데이터(스케줄링/프로파일) 수집
                final_candidates = self.data_provider.get_evidential_candidates(self.utid_n, self.utid_s)
                sched_md = self.data_provider.check_thread_scheduling(self.target_thread)
                profile_md = self.data_provider.profile_thread_functions(self.target_thread)

                # 부검 리포트 생성 및 데이터 아카이빙(JSON)
                final_report = self.build_final_report(
                    ai_response, sched_md, profile_md, investigation_id, self.target_thread
                )

                try:
                    json_path = self.data_collector.collect_point_scan_data(
                        scanner=self, 
                        ai_history=self.ai_analyst.history,
                        final_candidates=final_candidates,
                        final_report_md=final_report
                    )
                    self.output_callback(f"✅ [Handover] Point-Scan Investigation Sealed: {json_path}", True)
                except Exception as e:
                    self.output_callback(f"❌ [Critical] Failed to archive investigation: {str(e)}", True)
                
                self.output_callback(final_report)
                break

            # [CASE B: 백트랙] 가설 파괴로 인한 이전 경로 회귀
            if "Backtrack" in target_slice:
                if self.backtrack_count < self.backtrack_limit:
                    self.backtrack_count += 1
                    self.output_callback(f"🔄 Backtrack ({self.backtrack_count}/{self.backtrack_limit})")
                    
                    if len(self.scope_stack) > 1:
                        self.scope_stack.pop() # 이전 스코프로 복원
                        self.ai_analyst.trim_last_cfs_data() 
                    
                    ts_n, ts_s = self.scope_stack[-1]
                    cfs_block = self.data_provider.generate_cfs(
                        self.utid_n, ts_n, self.utid_s, ts_s, exclude_scopes=self.investigated_scopes
                    )
                else:
                    # 백트랙 한도 초과 시 AI에게 현재 스코프 고수 압박
                    self.output_callback("🚫 [Hard-Limit] Backtrack limit reached! Forcing AI to stay on path.", True)
                    cfs_block = ("⚠️ [Notice] Backtrack limit (2/2) reached. You MUST proceed with current data. "
                                 f"Re-analyze current scope: {self.scope_stack[-1]}")
                
                current_round += 1
                continue

            # [CASE C: 정밀 타격] 새로운 하위 슬라이스로 수사 범위 좁히기 (Drill-down)
            new_ts_n = self.data_provider.get_slice_bounds("normal", self.utid_n, target_slice)
            new_ts_s = self.data_provider.get_slice_bounds("slow", self.utid_s, target_slice)

            n_str = f"{new_ts_n[0]}-{new_ts_n[1]}" if new_ts_n else "None"
            s_str = f"{new_ts_s[0]}-{new_ts_s[1]}" if new_ts_s else "None"
            self.output_callback(f"🎯 [Targeted Strike] {target_slice} | N:{n_str} | S:{s_str}", True)

            if new_ts_s:
                # 중복 분석 방지 및 스택 업데이트
                scope_key = (tuple(new_ts_n or []), tuple(new_ts_s))
                if scope_key in self.investigated_scopes:
                    cfs_block = f"⚠️ [Notice] '{target_slice}' already analyzed. Pivot to a different Sibling or 'Backtrack'."
                else:
                    self.investigated_scopes.append(scope_key)
                    self.scope_stack.append((new_ts_n, new_ts_s))
                    cfs_block = self.data_provider.generate_cfs(self.utid_n, new_ts_n, self.utid_s, new_ts_s)
                    self.output_callback(f"✅ Data Refined: {target_slice}", True)
                current_round += 1
            else:
                # 슬라이스 탐색 실패 시 에러 피드백
                cfs_block = f"⚠️ [Error] Slice '{target_slice}' not found. Check names or 'Backtrack'."
                current_round += 1

        self.output_callback("\n✅ [Point-Scan] Investigation Concluded.")

    def build_final_report(self, ai_response, sched_md, profile_md, investigation_id, thread_name):
        def extract(tag):
            # 1. 태그 추출 정규식: [TAG], **TAG**, TAG: 등 다양한 변종 대응
            # 다음 태그가 나오거나 줄바꿈+태그가 나오기 전까지의 모든 내용을 긁어옵니다.
            pattern = rf"(?:\[{tag}\]|\*\*{tag}\*\*|{tag})\s*[:：]?\s*(.*?)(?=\n\s*\[|\n\s*\*\*|\n\s*[A-Z][:：]|$)"
            match = re.search(pattern, ai_response, re.DOTALL | re.IGNORECASE)
            
            if match:
                # 마크다운 잔여물 및 불필요한 공백 제거
                content = match.group(1).strip()
                return content.replace("**", "").replace("[", "").replace("]", "").strip()
            
            # 2. [REASONING] 태그 부재 시 <think> 태그에서 요약본 추출 (Fallback)
            if tag in ["REASONING", "C"]:
                think_match = re.search(r"<think>(.*?)</think>", ai_response, re.S)
                if think_match and tag == "REASONING":
                    text = think_match.group(1).strip()
                    return (text[:300] + "...") if len(text) > 300 else text
                    
            return "N/A"

        # 데이터 추출 (L1 전용 태그 맵핑)
        verdict = extract("V")  # 판결 (🔴, ⚠️, ✅)
        owner = extract("O")    # 책임 소재 (📱 App, 🏛️ Framework 등)
        cause = extract("C")    # 원인 분석 (한글)
        app_pct = extract("A")  # 앱 비중
        sys_pct = extract("S")  # 시스템 비중
        actions = extract("T")  # 권고 조치

        # 3. 리포트 마크다운 구조화 (가독성 중심)
        report = (
            f"# 🕵️‍♂️ FUSION-CORE FORENSIC REPORT (L1-Point)\n"
            f"**Invest-ID:** `{investigation_id}` | **Target:** `{thread_name}`\n"
            f"**Verdict:** {verdict} | **Responsible:** {owner}\n"
            f"{'='*70}\n\n"
            
            f"### 🚨 핵심 부검 결론 (Verdict Summary)\n"
            f"> **{cause}**\n\n"
            
            f"#### 📊 지연 책임 배분 (Responsibility)\n"
            f"| 구분 | 비중 (%) | 책임 주체 |\n"
            f"| :--- | :--- | :--- |\n"
            f"| **📱 Application** | `{app_pct}%` | {owner if 'App' in owner else '-'} |\n"
            f"| **⚙️ System/Kernel** | `{sys_pct}%` | {owner if 'App' not in owner else '-'} |\n\n"
            
            f"{'-'*70}\n"
            f"### 🔬 물리적 증거 분석 (Physical Evidence)\n"
            f"#### ⏳ 스케줄링 델타 (Scheduling Delta)\n"
            f"{sched_md}\n\n"
            
            f"#### 📈 함수 실행 프로파일 (Function Profile)\n"
            f"{profile_md}\n\n"
            
            f"{'-'*70}\n"
            f"### 🛠️ 전략적 대응 방안 (Action Items)\n"
            f"**수사관 권고 사항:**\n"
            f"{actions}\n\n"
            
            f"---\n"
            f"*Reported by FusionCore 3.0 Sniper Engine*\n"
        )
        return report