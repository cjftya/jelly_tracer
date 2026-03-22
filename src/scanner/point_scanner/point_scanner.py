import re
import json
from datetime import datetime
from scanner.point_scanner.point_scan_data_delegate import PointScanDataDelegate
from scanner.point_scanner.point_scan_ai_delegate import PointScanAIDelegate
from scanner.base_scanner import BaseScanner

class PointScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        self.target_package = None
        
        # 각 분야의 전문가(Delegates) 소집
        self.data_provider = None  # SQL 기반 데이터 추출 엔진
        self.ai_analyst = None     # LLM 기반 추론 분석 전문가
        
        # 수사 진행 상태 저장 변수
        self.utid_n = None         # Normal 트레이스 타겟 스레드 ID
        self.utid_s = None         # Slow 트레이스 타겟 스레드 ID
        self.target_thread = None  # 분석 대상 스레드 이름

        self.milestones = None
        self.milestone_names = None
        self.milestone_start_index = 0
        self.milestone_end_index = 0

    def start(self, trace_normal, trace_slow, target_package, ollama_manager, analysis_data, output_callback):
        """수사 시작 전 전문가 객체들을 초기화합니다."""
        super().start(trace_normal, trace_slow, target_package, ollama_manager, analysis_data, output_callback)
        self.target_package = target_package
        self.data_provider = PointScanDataDelegate(output_callback)
        self.data_provider.init(trace_normal, trace_slow, target_package)
        self.ai_analyst = PointScanAIDelegate(ollama_manager, output_callback)

        self.milestones = self.data_provider.get_common_milestones()
        if self.milestones:
            self.milestone_names = [m['name'] for m in self.milestones]

    def run(self, output_callback=None):
        super().run(output_callback)
        if output_callback:
            self.data_provider.output_callback = output_callback
            self.ai_analyst.output_callback = output_callback

        self.output_callback(f"🚀 [Point-Scan] Investigation Started: {self.target_package}")
        
        # ---------------------------------------------------------
        # Step 1: 수사 대상 확정 (Targeting)
        # ---------------------------------------------------------
        # 양쪽 트레이스에서 가장 지연이 심하고 대조 가능한 스레드를 찾습니다.
        self.utid_n, self.utid_s, self.target_thread = self.data_provider.identify_targets()
        
        if not self.target_thread:
            self.output_callback("❌ [Failed] Identification failed. Structural mismatch detected.", True)
            return

        # ---------------------------------------------------------
        # Step 2: 증거 수집 (JSON Tree Generation)
        # ---------------------------------------------------------
        self.output_callback("\n📦 [Evidence] Generating high-precision JSON trees (Depth 3)...", True)

        if self.milestones:
            start_m = self.milestones[self.milestone_start_index]
            end_m = self.milestones[self.milestone_end_index]
        
        # AI 분석을 위한 고농축 JSON 데이터 생성
        json_report_data = self.data_provider.generate_point_scan_json(start_m, end_m)

        # 분석할 만한 유의미한 데이터가 없는 경우 종료
        if "error" in json_report_data or not json_report_data.get("worst_cases"):
            self.output_callback("⚠️ [Notice] No significant regression found in current scope.", True)
            self.output_callback("💡 Latency is below threshold. Ending investigation.", True)
            return

        # ---------------------------------------------------------
        # Step 3: AI 심문 (Analysis)
        # ---------------------------------------------------------
        self.output_callback("\n🤖 [AI Analyst] R1 investigator is analyzing the evidence...\n", True)

        # AI에게 전달하기 직전, 내부용 필드 제거
        clean_json_data = self.data_provider.get_clean_json_for_ai(json_report_data)
        
        # AI에게 전달할 패키지 구성 (JSON 직렬화 포함)
        ai_context = {
            "thread_name": self.target_thread,
            "utid_info": f"Slow:{self.utid_s} / Normal:{self.utid_n}",
            "tree_data": json.dumps(clean_json_data, separators=(',', ':'), ensure_ascii=False)
        }

        # AI 분석 실행 및 리포트 수신
        analysis_result = self.ai_analyst.request_analysis(ai_context)

        # ---------------------------------------------------------
        # Step 4: 최종 판결 보고 (Final Judgment)
        # ---------------------------------------------------------
        self.output_callback("\n⚖️ [Point Scan Report]")
        self.output_callback("=" * 60)
        
        if self.ai_analyst.thought_archive:
            self.output_callback("\n🧠 [AI Thought...]")
            self.output_callback("-" * 40)
            latest_thought = self.ai_analyst.thought_archive[-1]
            self.output_callback(f"{latest_thought}\n")
            self.output_callback("-" * 40)

        if analysis_result:
            self.output_callback("\n📋 [Result]")
            self.output_callback(analysis_result)
        else:
            self.output_callback("🚨 [Critical] No valid judgment received from AI.")
            
        self.output_callback("=" * 60)
        self.output_callback("\n✅ [Point-Scan] Investigation concluded successfully.")