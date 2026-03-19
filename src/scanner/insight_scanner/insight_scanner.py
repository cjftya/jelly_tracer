from scanner.base_scanner import BaseScanner
from scanner.insight_scanner.insight_scan_data_delegate import InsightScanDataDelegate
from scanner.insight_scanner.insight_scan_ai_delegate import InsightScanAIDelegate

class InsightScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        # Delegates
        self.data_provider = None
        self.ai_analyst = None

    def start(self, ollama_manager, output_callback):
        super().start(ollama_manager, output_callback)
        self.data_provider = InsightScanDataDelegate(output_callback)
        self.ai_analyst = InsightScanAIDelegate(ollama_manager, output_callback)
    
    def run(self, trace_normal, trace_slow, target_package, analysis_data=None):
        super().run(trace_normal, trace_slow, target_package, analysis_data)
        
        # 1. 공통 API 및 데이터 제공자 초기화
        self.data_provider.init(trace_normal, trace_slow, target_package)
        
        self.output_callback(f"🚀 [Insight-Scan] Investigation Started: {target_package}")

        # 2. L1 분석 데이터(Point-Scan 결과) 존재 확인
        if not analysis_data:
            self.output_callback("⚠️ [Error] No Point-Scan data found. Insight Scan requires L1 results.", True)
            return

        try:
            # 3. 5대 심연 수사 API 데이터 호출 (Drilling)
            # analysis_data['window'] 정보를 기반으로 특정 구간을 정밀 타격
            target_window = analysis_data.get('window', {})
            if not target_window.get('start') or not target_window.get('end'):
                self.output_callback("⚠️ [Error] Target window is invalid.", True)
                return
            
            top_candidates = analysis_data.get('intel', {}).get('top_candidates', [])
            if not top_candidates:
                self.output_callback("⚠️ [Error] No top candidates found. Cannot proceed with deep dive.", True)
                return

            self.output_callback("🔬 Drilling into trace layers (Stacks, Locks, Neighbors, Rhythm, Binder)...")
            deep_dive_package = self.data_provider.fetch_deep_dive_package(target_window)

            # 4. L2 마스터 브리핑 패키지 조립
            # L1의 통찰(intel)과 델리게이트가 긁어온 원본 데이터를 통합
            master_brief = {
                "target_header": {
                    "package": target_package,
                    "thread": analysis_data.get('header', {}).get('thread'),
                    # 전체 분석 윈도우 길이를 ms로 환산하여 AI에게 기준점 제공
                    "window_ms": round((analysis_data['window']['end'] - analysis_data['window']['start']) / 1e6, 2)
                },
                "l1_forensic_intel": analysis_data.get('intel', {}),
                "l1_constraints": analysis_data.get('constraints', {}),
                "deep_dive_evidence": deep_dive_package, # SQL 결과 (모두 ms 단위)
                "top_candidates": top_candidates,
            }

            # 5. 2단계 AI 추론 엔진 가동 (Phase 1: 탐사 -> Phase 2: 검토)
            # 결과물은 [FINAL_INSIGHT] 포맷의 최종 리포트
            self.output_callback("🧠 AI Analyst is synthesizing deep insights...")
            final_verdict = self.ai_analyst.execute_double_scan(master_brief)

            # 6. 최종 결과 출력 및 수사 종료
            self.output_callback("\n" + "="*50)
            self.output_callback(final_verdict)
            self.output_callback("✅ [Insight-Scan] All investigations concluded.")
            self.output_callback("="*50 + "\n")

        except Exception as e:
            self.output_callback(f"❌ [Critical Error] Insight Scan failed: {str(e)}", True)

    def stop(self):
        pass