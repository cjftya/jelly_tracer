import re
from datetime import datetime
from scanner.point_scanner.point_scan_data_delegate import PointScanDataDelegate
from scanner.point_scanner.point_scan_ai_delegate import PointScanAIDelegate
from scanner.base_scanner import BaseScanner

class PointScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        self.target_package = None
        
        # Delegates
        self.data_provider = None
        self.ai_analyst = None
        
        # State
        self.utid_n = None
        self.utid_s = None
        self.target_thread = None

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
            self.output_callback("❌ Fail: Could not identify target threads. Structural mismatch detected.", True)
            return

        # ---------------------------------------------------------
        # 2. 증거 수집 (L1 Delta Tree Generation)
        # ---------------------------------------------------------
        self.output_callback("\n📦 [Evidence] Generating L1 Delta Trees (Depth 3)...", True)
        l1_report_data = self.data_provider.get_l1_delta_packages()
        
        # [Zero Delta Case 처리]
        if "⚠️ [Notice]" in l1_report_data:
            self.output_callback(f"{l1_report_data}", True)
            self.output_callback("💡 Latency is below the threshold or unchanged. Ending investigation.", True)
            return

        # ---------------------------------------------------------
        # 3. AI 심문 (Analysis)
        # ---------------------------------------------------------
        self.output_callback("\n🤖 [AI Analyst] reviewing the evidence...", True)
        
        # AI에게 전달할 컨텍스트 구성
        ai_context = {
            "thread_name": self.target_thread,
            "utid_info": f"S:{self.utid_s} / N:{self.utid_n}",
            "tree_data": l1_report_data
        }
        
        # AI 분석 실행 (PointScanAIDelegate를 통해 LLM 호출)
        analysis_result = self.ai_analyst.request_analysis(ai_context)

        # ---------------------------------------------------------
        # 4. 최종 판결 및 출력 (Final Judgment)
        # ---------------------------------------------------------
        self.output_callback("\n⚖️ [Final Judgment]", True)
        self.output_callback("-" * 60, True)
        self.output_callback(analysis_result, True) # AI의 최종 리포트 출력
        self.output_callback("-" * 60, True)

        # self.output_callback("\n✅ [Point-Scan] Investigation Concluded.")