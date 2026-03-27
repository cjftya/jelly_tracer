import re
import json
from datetime import datetime
from scanner.point_scanner.point_scan_data_delegate import PointScanDataDelegate
from scanner.point_scanner.point_scan_ai_delegate import PointScanAIDelegate
from scanner.base_scanner import BaseScanner
from log import Logger

class PointScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        self.data_provider = None  # SQL 기반 데이터 추출 엔진
        self.ai_analyst = None     # LLM 기반 추론 분석 전문가
        
        self.utid_n = None         # Normal 트레이스 타겟 스레드 ID
        self.utid_s = None         # Slow 트레이스 타겟 스레드 ID
        self.target_thread = None  # 분석 대상 스레드 이름

        self.milestones = None
        self.milestone_names = None
        self.milestone_start_index = 0
        self.milestone_end_index = 0

    def start(self, common_api, target_package, ollama_manager, output_callback):
        super().start(common_api, target_package, ollama_manager, output_callback)
        self.data_provider = PointScanDataDelegate(output_callback)
        self.data_provider.init(common_api, target_package)
        self.ai_analyst = PointScanAIDelegate(ollama_manager, output_callback)

        self.milestones = self.data_provider.get_common_milestones()
        if self.milestones:
            self.milestone_names = [m['name'] for m in self.milestones]

    def stop(self):
        super().stop()

    def run(self, output_callback=None):
        super().run(output_callback)
        if output_callback:
            self.data_provider.output_callback = output_callback
            self.ai_analyst.output_callback = output_callback

        self.output_callback(f"🚀 [Point-Scan] Investigation Started: {self.target_package}")
        
        # ---------------------------------------------------------
        # Step 1: 수사 대상 확정 (Targeting)
        # ---------------------------------------------------------
        # 양쪽 트레이스에서 가장 지연이 심하고 대조 가능한 스레드를 특정합니다.
        self.utid_n, self.utid_s, self.target_thread = self.data_provider.identify_targets()
        
        if not self.target_thread:
            self.output_callback("❌ [Failed] Identification failed. Structural mismatch detected.", True)
            return None

        # ---------------------------------------------------------
        # Step 2: 증거 수집 (JSON Tree Generation)
        # ---------------------------------------------------------
        self.output_callback("\n📦 [Evidence] Generating high-precision JSON trees (Depth 3)...", True)

        if self.milestones:
            start_m = self.milestones[self.milestone_start_index]
            end_m = self.milestones[self.milestone_end_index]
        
        # AI 분석을 위한 고농축 JSON 데이터 생성 (가독성 및 토큰 효율화)
        json_report_data = self.data_provider.generate_point_scan_json(start_m, end_m)

        # 분석할 만한 유의미한 데이터가 없는 경우 종료
        if "error" in json_report_data or not json_report_data.get("worst_cases"):
            self.output_callback("⚠️ [Notice] No significant regression found in current scope.", True)
            self.output_callback("💡 Latency is below threshold. Ending investigation.", True)
            return None

        # ---------------------------------------------------------
        # Step 3: AI 심문 (Analysis)
        # ---------------------------------------------------------
        self.output_callback("\n🤖 [AI Analyst] Investigator is analyzing the evidence...\n", True)

        # AI에게 전달하기 직전, 내부용 필드(__internal_*) 제거 (보안 및 토큰 절약)
        clean_json_data = self.data_provider.get_clean_json_for_ai(json_report_data)
        
        # AI 분석 컨텍스트 구성
        ai_context = {
            "thread_name": self.target_thread,
            "utid_info": f"Slow:{self.utid_s} / Normal:{self.utid_n}",
            "tree_data": json.dumps(clean_json_data, separators=(',', ':'), ensure_ascii=False)
        }

        # AI 분석 실행 및 결과 수신 (thinking, analysis 포함)
        analysis_result = self.ai_analyst.request_analysis(ai_context)

        Logger.log(f"PointScan response\n{analysis_result}")

        # 분석 결과 출력
        self.output_callback(f"\n🧠 [AI Thinking...]\n{analysis_result['thinking']}\n")
        self.output_callback(f"\n📋 [AI Analysis...]\n{analysis_result['analysis']}\n")

        self.output_callback("✅ [Point-Scan] Investigation concluded successfully.\n\n")

        # 수집된 데이터를 최종 마스터 데이터로 통합
        return self.collect_analyze_data(analysis_result, json_report_data)

    def collect_analyze_data(self, ai_result, raw_json_data):
        # 1. 마일스톤 좌표 확보
        start_node = self.milestones[self.milestone_start_index]
        end_node = self.milestones[self.milestone_end_index]
        total_delay_ms = end_node['delta_ms'] - start_node['delta_ms']

        # 2. AI 리포트에서 단일 타겟 파싱 (정규표현식 활용)
        # 분석 본문(analysis)에서 범인의 Case ID, Target-Id, Duration을 찾아냅니다.
        report_text = ai_result['analysis']
        pattern = re.compile(
            r"""
            -?\s*[Cc]ase:\s*(?P<case_id>[^(\r\n]+).*?[\r\n]+      
            -?\s*Target-Id:\s*(?P<target_id>\d+).*?[\r\n]+       
            -?\s*Duration:\s*(?P<duration>[\d.]+)\s*ms.*?[\r\n]* """, 
            re.VERBOSE | re.IGNORECASE | re.MULTILINE
        )
        
        match = pattern.search(report_text)
        if not match:
            self.output_callback("🚨 [Critical] Failed to parse target from AI report.", True)
            return None

        data = match.groupdict()
        root_target_id = int(data["target_id"])
        target_info = {
            "case_id": data["case_id"],
            "target_id": root_target_id,
            "duration_ms": float(data["duration"])
        }

        # 3. [재귀 탐색] Raw JSON 트리에서 물리 좌표(__internal_*) 추출
        # AI는 ID만 알려주므로, 실제 DB에 접근할 수 있는 ts와 dur를 다시 찾아야 합니다.
        def find_internal_coords(node, target_id):
            if node.get("target_id") == target_id:
                return {
                    "start_ts_ns": node.get("__internal_ts"),
                    "duration_ns": node.get("__internal_dur"),
                    "utid": node.get("__internal_utid")
                }
            
            for child in node.get("children", []):
                found = find_internal_coords(child, target_id)
                if found: return found
            return None

        internal_data = {}
        if raw_json_data.get("worst_cases"):
            # 워스트 케이스 트리(index 0)를 훑어 좌표를 복원합니다.
            root_tree = raw_json_data["worst_cases"][0].get("tree", {})
            internal_data = find_internal_coords(root_tree, target_info["target_id"]) or {}

        # 4. 데이터 통합 및 좌표 검증 (Fallback 로직 포함)
        if not internal_data.get("start_ts_ns"):
            self.output_callback(f"⚠️ [Warning] System coordinates not found for ID: {target_info['target_id']}", True)
            # 좌표를 못 찾으면 마일스톤 시작점을 기본값으로 사용
            internal_data = {
                "start_ts_ns": start_node['ts_s'], 
                "duration_ns": 0, 
                "utid": internal_data.get("utid")
            }

        target_info.update(internal_data)

        # 5. 최종 마스터 데이터 조립 (인사이트 스캔 등으로 전달될 자료)
        master_data = {
            "milestones": {
                "start_name": start_node['name'],
                "end_name": end_node['name'],
                "start_ts_ns": start_node['ts_s'], 
                "end_ts_ns": end_node['ts_s'],
                "start_index": self.milestone_start_index,
                "end_index": self.milestone_end_index,
                "total_delay_ms": total_delay_ms
            },
            "target_data": target_info,
            "report_data": ai_result,
            "ai_thought": getattr(self.ai_analyst, 'thought_archive', [])
        }

        return master_data