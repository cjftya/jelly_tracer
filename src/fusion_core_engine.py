from scanner.base_scanner import BaseScanner
from scanner.point_scanner.point_scanner import PointScanner
from scanner.insight_scanner.insight_scanner import InsightScanner
from common_api import CommonAPI

class FusionCoreEngine:
    def __init__(self):
        self.output_callback = None
        self.ollama_manager = None
        self.range_callback = None

        self.trace_normal = None
        self.trace_slow = None
        self.target_package = None

        self.point_scanner = PointScanner()
        self.insight_scanner = InsightScanner()

        self.common_api = None
    def start(self, ollama_manager, output_callback, range_callback=None):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.range_callback = range_callback

    def load(self, trace_normal, trace_slow, target_package):
        self.trace_normal = trace_normal
        self.trace_slow = trace_slow
        self.target_package = target_package
        self.common_api = CommonAPI(trace_normal, trace_slow, target_package)
        
        self.point_scanner.start(self.common_api, self.target_package, self.ollama_manager, self.output_callback)

        if self.range_callback:
            self.range_callback(self.point_scanner.milestone_names)

        self.insight_scanner.start(self.common_api, self.target_package, self.ollama_manager, self.output_callback)

    def run(self, output_callback=None, start_m_index=0, end_m_index=0):
        if output_callback:
            self.output_callback = output_callback
        
        self.point_scanner.milestone_start_index = start_m_index
        self.point_scanner.milestone_end_index = end_m_index
        collected_data = self.point_scanner.run(output_callback=output_callback)

        output_callback("\\token_zero")

        self.insight_scanner.collected_data = collected_data
        final_result = self.insight_scanner.run(output_callback=output_callback)
        
    def stop(self):
        pass

    def _testData(self):
        return {
                "milestones": {
                    "start_name": "activityResume",
                    "end_name": "VisualComplete",
                    "start_ts_ns": 106676020944917,
                    "end_ts_ns": 106681518444550,
                    "start_index": 2,
                    "end_index": 3,
                    "total_delay_ms": 652.13
                },
                "target_data": {
                    "case_id": "WC-001",
                    "target_id": 128971,
                    "duration_ms": 75.8,
                    "start_ts_ns": 106676097521167,
                    "duration_ns": 75763541,
                    "utid": 1529
                },
                "report_data": "**[Selected Slice]**\n- Case: WC-001\n- Target-Id: 128971\n- Duration: 75.8ms\n\n**[Detailed Reason]**\n- The node with target_id 128971 represents the largest regression with a delta_time of 75.8ms, significantly impacting the overall performance. Its high delta_time and impact_ratio make it the primary suspect for causing delays in the system.",
                "ai_thought": [
                    "Alright, I need to figure out which target_id is the most critical based on the given JSON data. Let's break down the steps.\n\nFirst, I'll look at the two cases: WC-001 and WC-002. The goal is to find the node with the highest delta_time because that's the biggest bottleneck.\n\nIn WC-001, the total duration is 75.8ms. The tree shows several nodes. The root node has a delta_time of 75.8ms. Looking deeper, there's a draw-VRI[GalleryActivity] with a delta_time of 65.8ms. That's quite significant.\n\nIn WC-002, the total duration is 49.6ms, but the highest delta_time here is 29.7ms in the activityResume node. Comparing this to WC-001, 75.8ms is much higher than 29.7ms, so even though both have high deltas, WC-001's root node is more concerning.\n\nNext, I check the impact_ratio. For WC-001, the root has an impact_ratio of 1.0, which is the highest possible. In WC-002, it's also 1.0, but since the delta is smaller, WC-001's node is still more critical.\n\nI also need to ensure that the selected target_id and delta_time match exactly from the JSON. The root node in WC-001 has target_id 128971 with a delta_time of 75.8ms, which fits perfectly.\n\nSo, based on the analysis, WC-001's root node is the primary suspect because it has the highest delta_time and the highest impact_ratio, making it the most critical target."
                ]
        }