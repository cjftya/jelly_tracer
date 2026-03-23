from scanner.base_scanner import BaseScanner
from scanner.insight_scanner.insight_scan_data_delegate import InsightScanDataDelegate
from scanner.insight_scanner.insight_scan_ai_delegate import InsightScanAIDelegate

class InsightScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        self.collected_data = None  # 1차 분석 결과(마스터 데이터)
        self.data_provider = None
        self.ai_analyst = None

    def start(self, common_api, target_package, ollama_manager, output_callback):
        super().start(common_api, target_package, ollama_manager, output_callback)
        if self.data_provider is None:
            self.data_provider = InsightScanDataDelegate(output_callback)
            self.data_provider.init(common_api, target_package)
        else:
            self.data_provider.output_callback = output_callback
            
        if self.ai_analyst is None:
            self.ai_analyst = InsightScanAIDelegate(ollama_manager, output_callback)
        else:
            self.ai_analyst.output_callback = output_callback
    
    def run(self, output_callback=None):  
        if output_callback:
            self.output_callback = output_callback
            self.data_provider.output_callback = output_callback
            self.ai_analyst.output_callback = output_callback
        
        self.output_callback(f"🚀 [Insight-Scan] Investigation Started: {self.target_package}")

        # 1. 마스터 데이터 존재 확인
        if not self.collected_data:
            self.output_callback("⚠️ [Error] Master data (collected_data) is missing. Cannot proceed.", True)
            return

        try:
            # 2. 2차 심층 데이터 추출 (SQL Drilling)
            # 수정된 Delegate는 collected_data를 직접 받아 25/20/10 데이터를 추출합니다.
            self.output_callback("🔬 Drilling into trace layers (Stacks, Binder, Locks)...")
            deep_dive_evidence = self.data_provider.fetch_deep_dive_package(self.collected_data)

            if not deep_dive_evidence:
                return

            # 3. 최종 AI 분석용 마스터 브리핑 패키지 조립 (JSON 통합)
            # 1차의 컨텍스트와 2차의 물리적 증거를 결합합니다.
            master_brief = {
                "analysis_context": self.collected_data, 
                "deep_dive_evidence": deep_dive_evidence 
            }

            # 4. 2단계 AI 추론 엔진 가동 (Phase 1: 탐사 -> Phase 2: 검증)
            self.output_callback("🧠 AI Analyst is synthesizing deep insights...")
            final_verdict = self.ai_analyst.execute_double_scan(master_brief)

            # 5. 최종 결과 출력 및 수사 종료
            self.output_callback("\n" + "="*50)
            self.output_callback(final_verdict)
            self.output_callback("\n✅ [Insight-Scan] All investigations concluded.")
            self.output_callback("="*50 + "\n")

        except Exception as e:
            self.output_callback(f"❌ [Critical Error] Insight Scan failed: {str(e)}", True)

    def stop(self):
        pass