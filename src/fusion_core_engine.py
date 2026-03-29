import gc
from scanner.point_scanner.point_scanner import PointScanner
from scanner.insight_scanner.insight_scanner import InsightScanner
from analysis.fast_analysis import FastAnalysis
from analysis.deep_analysis import DeepAnalysis
from common_api import CommonAPI
from log import Logger

class FusionCoreEngine:
    def __init__(self):
        self.output_callback = None
        self.llm_requester = None
        self.range_callback = None

        self.trace_normal = None
        self.trace_slow = None
        self.target_package = None

        self.point_scanner = PointScanner()

        self.fast_analysis = FastAnalysis()
        self.deep_analysis = DeepAnalysis()
        self.mode = None

        self.common_api = None

    def start(self, llm_requester, output_callback, range_callback=None):
        self.output_callback = output_callback
        self.llm_requester = llm_requester
        self.range_callback = range_callback

    def load(self, trace_normal, trace_slow, target_package, mode="Fast Analysis"):
        self.trace_normal = trace_normal
        self.trace_slow = trace_slow
        self.target_package = target_package
        self.mode = mode
        self.common_api = CommonAPI(trace_normal, trace_slow, target_package)
        
        self.point_scanner.start(self.common_api, self.target_package, self.llm_requester, self.output_callback)

        if self.range_callback:
            self.range_callback(self.point_scanner.milestone_names)

        if self.is_fast_analysis():
            self.fast_analysis.start(self.common_api, self.target_package, self.llm_requester, self.output_callback)
        elif self.is_deep_analysis():
            self.deep_analysis.start(self.common_api, self.target_package, self.llm_requester, self.output_callback)

    def run(self, output_callback=None, start_m_index=0, end_m_index=0):
        if output_callback:
            self.output_callback = output_callback
        
        self.point_scanner.milestone_start_index = start_m_index
        self.point_scanner.milestone_end_index = end_m_index
        collected_data = self.point_scanner.run(output_callback=output_callback)

        if collected_data is None:
            self.output_callback("⚠️ [Error] Collected data is missing. Cannot proceed.", True)
            return

        Logger.log(collected_data)

        if self.is_fast_analysis():
            self.fast_analysis.run(collected_data, output_callback=output_callback)
        elif self.is_deep_analysis():
            self.deep_analysis.run(collected_data, output_callback=output_callback)
        
    def stop(self):
        if self.point_scanner:
            self.point_scanner.stop()
        if self.is_fast_analysis():
            self.fast_analysis.stop()
        elif self.is_deep_analysis():
            self.deep_analysis.stop()

        if self.common_api:
            self.common_api.release()

        gc.collect()

    def is_fast_analysis(self):
        return self.mode == "Fast Analysis"

    def is_deep_analysis(self):
        return self.mode == "Deep Analysis"