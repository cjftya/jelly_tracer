import json
from scanner.point_scanner.point_scan_data_delegate import PointScanDataDelegate
from scanner.base_scanner import BaseScanner
from log import Logger

class PointScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        self.data_provider = None
        
        self.milestones = None
        self.milestone_names = None
        self.milestone_marks = None
        self.milestone_start_index = -1
        self.milestone_end_index = -1

    def start(self, common_api, target_package, llm_requester, output_callback):
        super().start(common_api, target_package, llm_requester, output_callback)

        self.data_provider = PointScanDataDelegate(output_callback)
        self.data_provider.init(common_api)

        self.milestones = self.data_provider.calculate_common_milestones()
        self.milestone_names = [m['name'] for m in self.data_provider.milestones_registry]
        self.milestone_marks = self.data_provider.milestone_marks

    def stop(self):
        super().stop()

    def run(self, output_callback=None):
        super().run(output_callback)
        if output_callback:
            self.data_provider.output_callback = output_callback

        self.output_callback(f"🚀 [Point-Scan] Global Investigation Started: {self.target_package}")
        
        # ---------------------------------------------------------
        # Step 1: 전수 조사 실행 (Global Point-Scan)
        # ---------------------------------------------------------
        point_scan_result = self.data_provider.run_point_scan(
            target_package_name=self.target_package,
            start_milestone_index=self.milestone_start_index,
            end_milestone_index=self.milestone_end_index
        )

        # 분석할 만한 유의미한 데이터가 없는 경우 종료
        if not point_scan_result or not point_scan_result.get("incidents"):
            self.output_callback("⚠️ [Notice] No significant delay incidents found in current scope.", True)
            return None

        # ---------------------------------------------------------
        # Step 2: 마스터 데이터 조립 (Data Packaging)
        # ---------------------------------------------------------
        final_master_data = self.collect_analyze_data(point_scan_result)

        self.output_callback("✅ [Point-Scan] Evidence collection concluded. Ready for Analysis Phase.\n\n")

        return final_master_data

    def collect_analyze_data(self, point_scan_result):
        # 1. 마일스톤 좌표 확보
        start_milestone_data = self.milestones[self.milestone_start_index]
        end_milestone_data = self.milestones[self.milestone_end_index]
        
        # 2. 최종 마스터 데이터 조립
        master_data = {
            "milestone_info": {
                "start_name": start_milestone_data['name'],
                "end_name": end_milestone_data['name'],
                "start_ts_ns": start_milestone_data['ts_s_start'], 
                "end_ts_ns": end_milestone_data['ts_s_end'],
                "start_index": self.milestone_start_index,
                "end_index": self.milestone_end_index,
                "total_delay_ms": point_scan_result['analysis_metadata']['total_delay_ms']
            },
            "normal_baseline": point_scan_result['normal_baseline'],
            "analysis_metadata": point_scan_result['analysis_metadata'],
            "incidents": point_scan_result['incidents']
        }

        # 로깅: 수집된 사건의 요약 정보를 기록
        Logger.log(f"PointScan Results Collected: {len(master_data['incidents'])} incidents found.")
        
        return master_data