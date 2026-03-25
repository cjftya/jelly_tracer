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
        
        # self.point_scanner.milestone_start_index = start_m_index
        # self.point_scanner.milestone_end_index = end_m_index
        # collected_data = self.point_scanner.run(output_callback=output_callback)
        # print(collected_data)

        # output_callback("\\token_zero")

        collected_data = self._testData()

        self.insight_scanner.collected_data = collected_data
        final_result = self.insight_scanner.run(output_callback=output_callback)
        
    def stop(self):
        pass

    def _testData(self):
            return {
                'milestones': {
                    'start_name': 'activityResume', 
                    'end_name': 'VisualComplete', 
                    'start_ts_ns': 106676020944917, 
                    'end_ts_ns': 106681518444550
                }, 
                'target_data': {
                    'case_id': 'WC-001', 
                    'target_id': 130562, 
                    'duration_ms': 65.8, 
                    'start_ts_ns': 106676107443042, 
                    'duration_ns': 65833906, 
                    'utid': 1529
                }, 
                'report_data': '**[Selected Slice]**\n\n- Case: WC-001\n- Target-Id: 130562\n- Duration: 65.8ms\n...', 
                'ai_thought': [
                    "Okay, I need to analyze the performance issues based on the provided JSON data...",
                    "The tree shows that the main node is this draw-VRI method with a delta_time of 65.8ms..."
                ]
            }