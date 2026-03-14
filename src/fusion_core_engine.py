from src.fusion_data_delegate import FusionDataDelegate
from src.fusion_ai_delegate import FusionAIDelegate

class FusionCoreEngine:
    def __init__(self):
        self.max_round = 8
        
        # Delegates
        self.data_provider = None
        self.ai_analyst = None
        
        # State
        self.utid_n = None
        self.utid_s = None
        self.output_callback = None
        self.investigated_scopes = []
        self.target_thread = None

    def start(self, ollama_manager, output_callback):
        self.output_callback = output_callback
        self.data_provider = FusionDataDelegate(output_callback)
        self.ai_analyst = FusionAIDelegate(ollama_manager, output_callback)

    def run(self, trace_normal, trace_slow, target_package):
        self.data_provider.init(trace_normal, trace_slow, target_package)
        self.output_callback(f"🚀 [Fusion-Core] Investigation Started: {target_package}")
        
        # 1. 타겟 락온 (UTID가 달라도 '이름'으로 매칭하여 각각 확보)
        # identify_targets에서 (utid_n, utid_s, thread_name)을 반환하도록 설계 권장
        self.utid_n, self.utid_s, self.target_thread = self.data_provider.identify_targets()
        if self.target_thread:
            self.output_callback(f"🎯 [Target Locked] Thread: {self.target_thread}")
            self.output_callback(f"🔗 Match Mapping: Normal(UTID:{self.utid_n}) <-> Slow(UTID:{self.utid_s})")
        else:
            self.output_callback("❌ Fail: Could not identify target threads.")
            return
        
        # 2. 초동 수사 (Round 1)
        ts_s = self.data_provider.get_global_bounds("slow")
        ts_n = self.data_provider.get_sync_bounds("normal", ts_s)
        cfs_block = self.data_provider.generate_cfs(self.utid_n, ts_n, self.utid_s, ts_s)
        
        current_round = 1
        while current_round <= self.max_round:
            self.output_callback(f"📡 [Round {current_round}] AI Analyzing...")
            # 수정: current_round 인자 추가
            ai_response = self.ai_analyst.request_analysis(current_round, cfs_block)
            
            # AI의 추론 과정 출력 (English Reasoning)
            thinking, _ = self.get_ai_thinking(ai_response)
            if thinking:
                self.output_callback(f"🤖 [AI Thinking] {thinking}")
            
            target_slice = self.ai_analyst.parse_slice_request(ai_response)
            
            if target_slice:
                self.output_callback(f"🎯 [Targeted Strike] Searching for Slice: {target_slice}")
                new_ts_n = self.data_provider.get_slice_bounds("normal", self.utid_n, target_slice)
                new_ts_s = self.data_provider.get_slice_bounds("slow", self.utid_s, target_slice)

                # ⚠️ 로지컬 에러 수정: Normal에 해당 슬라이스가 없을 경우의 Fallback
                if new_ts_s:
                    if not new_ts_n:
                        # 정상 트레이스에 해당 슬라이스가 없으면, 시간 동기화(Sync) 기반으로 대조군 생성
                        self.output_callback(f"⚠️ Notice: '{target_slice}' not found in Normal. Using sync-fallback.")
                        new_ts_n = self.data_provider.get_sync_bounds("normal", new_ts_s)
                    
                    # 중복 조사 체크
                    scope_key = (tuple(new_ts_n), tuple(new_ts_s))
                    if scope_key in self.investigated_scopes:
                        cfs_block = f"⚠️ [Duplicate Scope] Already analyzed '{target_slice}'. Look for other causes."
                        self.output_callback(f"🚫 Redundant request: {target_slice}")
                    else:
                        self.investigated_scopes.append(scope_key)
                        ts_n, ts_s = new_ts_n, new_ts_s
                        cfs_block = self.data_provider.generate_cfs(self.utid_n, ts_n, self.utid_s, ts_s)
                        self.output_callback(f"✅ Data Refined: {target_slice}")
                    
                    current_round += 1
                else:
                    # Slow 트레이스조차 슬라이스가 없을 때
                    cfs_block = f"⚠️ Investigation Failure: Slice '{target_slice}' not found. Try another path."
                    self.output_callback(f"❌ Slice '{target_slice}' not found.")
                    current_round += 1
            else:
                # 🏁 최종 판결 단계: 별도의 LLM 디자이너에게 리포트 생성 요청
                self.output_callback("\n🎨 [Fusion-Core] 리포트 생성 중...")
                
                # 8라운드 요약 데이터 추출
                _, raw_ai_verdict = self.get_ai_thinking(ai_response)
                
                final_pretty_report = self.ai_analyst.request_final_report(
                    self.data_provider.check_thread_scheduling(self.target_thread),
                    self.data_provider.profile_thread_functions(self.target_thread),
                    raw_ai_verdict
                )
                
                self.output_callback("\n" + "="*50)
                self.output_callback(final_pretty_report)
                self.output_callback("="*50)
                break

        self.output_callback("✅ [Fusion-Core] Investigation Concluded.")

    def get_ai_thinking(self, raw_text):
        parts = raw_text.split("[RESULT]:")
        if len(parts) > 1:
            reasoning = parts[0].strip()  # [RESULT] 이전: 영어 추론 (Thinking)
            verdict = "[RESULT]:" + parts[1].strip() # [RESULT] 이후: 한국어 판결 (Verdict)
            return reasoning, verdict
        else:
            # [RESULT]가 없는 경우를 대비한 방어 코드
            return None, raw_text

    def generate_pretty_report(self, ai_response):
        # 1. API들로부터 마크다운 조각 수집
        scheduling_md = self.data_provider.check_thread_scheduling(self.target_thread)
        profile_md = self.data_provider.profile_thread_functions(self.target_thread)
        
        # 2. AI 응답에서 Reasoning과 Report 분리 (이전에 만든 함수 활용)
        _, clean_report = self.get_ai_thinking(ai_response) # [RESULT] 이후만 가져옴

        # 3. 최종 리포트 디자인 조립
        report_md = f"""
            # 🚀 FUSION-CORE FORENSIC REPORT
            > **Investigation ID:** `#TC-{self.target_package.upper()}`
            > **Generated At:** 2026-03-14 | **Analyst:** Fusion-AI v3.0

            ---

            ## 🚩 [FINAL VERDICT]
            {clean_report.split('[EVIDENCE]')[0]} 
            *(상세 판결은 하단 Evidence 섹션 참조)*

            ---

            ## 📊 [PHASE 1] SCHEDULING ANALYSIS
            > 스레드가 CPU를 기다렸는지, 아니면 외부 요인으로 멈췄는지 분석한 결과입니다.
            {scheduling_report}

            ---

            ## 🔬 [PHASE 2] FUNCTION PROFILING
            > 어떤 함수에서 지연(Delta)이 가장 크게 발생했는지 대조 분석한 결과입니다.
            {function_profile}

            ---

            ## 🕵️♂️ [PHASE 3] CAUSAL EVIDENCE & ACTION
            ### 📑 Investigation Narrative
            {clean_report.split('[EVIDENCE]')[1] if '[EVIDENCE]' in clean_report else "No detailed evidence provided."}

            ---
            **[Fusion-Core Engine]** | *Real-time System Forensics & Optimization*
            """
        return report_md