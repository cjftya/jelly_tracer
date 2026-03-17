import re
from datetime import datetime
from fusion_data_delegate import FusionDataDelegate
from fusion_ai_delegate import FusionAIDelegate

class FusionCoreEngine:
    def __init__(self):
        self.max_round = 8
        self.backtrack_limit = 2  # 💡 백트랙 최대 허용 횟수
        self.backtrack_count = 0  # 💡 현재 백트랙 누적 횟수
        
        # Delegates
        self.data_provider = None
        self.ai_analyst = None
        
        # State
        self.utid_n = None
        self.utid_s = None
        self.output_callback = None
        self.investigated_scopes = [] 
        self.target_thread = None
        self.scope_stack = [] 

    def start(self, ollama_manager, output_callback):
        self.output_callback = output_callback
        self.data_provider = FusionDataDelegate(output_callback)
        self.ai_analyst = FusionAIDelegate(ollama_manager, output_callback)

    def run(self, trace_normal, trace_slow, target_package):
        self.data_provider.init(trace_normal, trace_slow, target_package)
        self.output_callback(f"🚀 [Fusion-Core] Investigation Started: {target_package}")
        
        # 1. 타겟 락온 및 ID 생성
        self.utid_n, self.utid_s, self.target_thread = self.data_provider.identify_targets()
        if not self.target_thread:
            self.output_callback("❌ Fail: Could not identify target threads.", True)
            return
            
        investigation_id = f"FC-{datetime.now().strftime('%m%d-%H%M')}"
        self.output_callback(f"🎯 [Target Locked] Thread: {self.target_thread} | ID: {investigation_id}", True)

        # 2. 피봇 슬라이스 정찰 (Worst-case 탐색)
        pivot = self.data_provider.find_worst_slice(self.utid_n, self.utid_s)

        # 3. 피봇 기반 스코프 확정 (Temporal 레벨)
        ts_s = None
        ts_n = None
        if pivot:
            ts_s = self.data_provider.get_slice_bounds("slow", self.utid_s, pivot)

        # [Safety Check] 피봇을 찾았더라도 좌표 조회에 실패하면 전체 범위로 자동 전환
        if ts_s:
            ts_n = self.data_provider.get_sync_bounds("normal", ts_s)
            self.output_callback(f"🎯 [Focus Mode] Investigating '{pivot}' window.", True)
        else:
            ts_s = self.data_provider.get_global_bounds("slow")
            ts_n = self.data_provider.get_sync_bounds("normal", ts_s)
            self.output_callback("🌐 [Global Mode] No specific pivot found. Analyzing full trace.", True)

        self.scope_stack.append((ts_n, ts_s)) 
        
        cfs_block = self.data_provider.generate_cfs(self.utid_n, ts_n, self.utid_s, ts_s)
        
        current_round = 1
        while current_round <= self.max_round:
            is_final_round = (current_round == self.max_round)
            self.output_callback(f"\n📡 [Round {current_round}/{self.max_round}] Analyzing...")
            
            # AI 분석 요청
            ai_response = self.ai_analyst.request_analysis(current_round, cfs_block)
            
            # 라운드 모니터링: [REASONING] 출력
            reasoning = re.search(r"\[REASONING\]:(.*?)(?=\[|$)", ai_response, re.S)
            self.output_callback(f"🤖 [Thinking] {reasoning.group(1).strip() if reasoning else 'Analyzing...'}")
            
            # 다음 수사 타겟 추출
            target_slice = self.ai_analyst.parse_slice_request(ai_response)
            
            # [종결 조건]
            if not target_slice or "Case Closed" in target_slice or is_final_round:
                if is_final_round:
                    self.output_callback("⚠️ [Hard-Stop] Max rounds reached. Synthesizing data...", True)

                sched_md = self.data_provider.check_thread_scheduling(self.target_thread)
                profile_md = self.data_provider.profile_thread_functions(self.target_thread)

                final_report = self.build_final_report(
                    ai_response, sched_md, profile_md, investigation_id, self.target_thread
                )
                
                self.output_callback(final_report)
                break

            # 백트랙 처리 (Pivot & Purge)
            if "Backtrack" in target_slice:
                if self.backtrack_count < self.backtrack_limit:
                    self.backtrack_count += 1
                    self.output_callback(f"🔄 Backtrack ({self.backtrack_count}/{self.backtrack_limit})")
                    
                    if len(self.scope_stack) > 1:
                        self.scope_stack.pop() 
                        self.ai_analyst.trim_last_cfs_data() 
                    
                    ts_n, ts_s = self.scope_stack[-1]
                    cfs_block = self.data_provider.generate_cfs(
                        self.utid_n, ts_n, self.utid_s, ts_s, exclude_scopes=self.investigated_scopes
                    )
                else:
                    # 🚨 백트랙 한도 초과: 동일 스코프 유지하며 AI 압박
                    self.output_callback("🚫 [Hard-Limit] Backtrack limit reached! Forcing AI to stay on path.", True)
                    cfs_block = ("⚠️ [Notice] Backtrack limit (2/2) reached. You MUST proceed with current data. "
                                 f"Re-analyze current scope: {self.scope_stack[-1]}")
                
                current_round += 1
                continue

            # 3. 새로운 타겟 슬라이스 탐색 (Targeted Strike)
            new_ts_n = self.data_provider.get_slice_bounds("normal", self.utid_n, target_slice)
            new_ts_s = self.data_provider.get_slice_bounds("slow", self.utid_s, target_slice)
            self.output_callback(f"🎯 [Targeted Strike] Searching: {target_slice}, {new_ts_n}, {new_ts_s}", True)

            if new_ts_s:
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
                cfs_block = f"⚠️ [Error] Slice '{target_slice}' not found. Check names or 'Backtrack'."
                current_round += 1

        self.output_callback("\n✅ [Fusion-Core] Investigation Concluded.")

    def build_final_report(self, ai_response, sched_md, profile_md, investigation_id, thread_name):
        def extract(tag):
            # [O] 태그 추가 및 다양한 마크다운 스타일(Bold, Brackets 등) 대응 패턴
            # 뒤에 오는 태그를 미리 보고 멈추는 Lookahead 패턴 강화
            pattern = rf"(?:\*\*?|\[?)\s*{tag}\s*(?:\]?|\*\*?)\s*[:：]\s*(.*?)(?=\n\s*\[|\n\s*\*\*\[|\n\s*[A-Z]\[|#|$)"
            match = re.search(pattern, ai_response, re.DOTALL | re.IGNORECASE)
            if match:
                content = match.group(1).strip()
                # 불필요한 마크다운 기호 및 잔여 대괄호 제거
                return content.replace("**", "").replace("[", "").replace("]", "").strip()
            return "N/A"

        # 신규 태그 [O]를 포함한 데이터 추출
        data = {
            "V": extract("V"),  # Verdict
            "O": extract("O"),  # Responsible Owner (추가)
            "C": extract("C"),  # Cause (Korean)
            "A": extract("A"),  # App %
            "S": extract("S"),  # System %
            "T": extract("T")   # Task/Action
        }

        # 리포트 생성 (가독성 및 포렌식 스타일 강화)
        report = (
            f"\n# 🕵️‍♂️ FUSION-CORE FORENSIC REPORT (v2.0)\n"
            f"**ID:** `{investigation_id}` | **Thread:** `{thread_name}`\n"
            f"**Status:** {data['V']} | **Responsible:** {data['O']}\n"
            f"{'='*65}\n"
            f"### 🚨 EXECUTIVE SUMMARY\n"
            f"> **CAUSE:** {data['C']}\n\n"
            f"**Responsibility Allocation:**\n"
            f"- 📱 **Application:** `{data['A']}%` | ⚙️ **System/Kernel:** `{data['S']}%` \n"
            f"- **Primary Owner:** {data['O']}\n\n"
            f"{'-'*65}\n"
            f"### 📊 PHYSICAL EVIDENCE (PHYS)\n"
            f"#### ⏳ Thread Scheduling Logic (Delta Analysis)\n"
            f"{sched_md}\n\n"
            f"#### 🔬 Function Execution Profile (Top Slices)\n"
            f"{profile_md}\n\n"
            f"{'-'*65}\n"
            f"### 🛠️ STRATEGIC ACTION ITEMS\n"
            f"**Recommended Fixes:**\n"
            f"{data['T']}\n\n"
            f"---\n"
            f"*Generated by Fusion-Core Engine v2.0 (Integrated SSR Mode)*\n"
            f"*Scan Protocol: L1 Point Scan Completed*"
        )
        return report