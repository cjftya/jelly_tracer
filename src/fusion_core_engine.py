from scanner.base_scanner import BaseScanner
from scanner.point_scanner.point_scanner import PointScanner
from scanner.insight_scanner.insight_scanner import InsightScanner
from fusion_core_data_parser import FusionCoreDataParser

class FusionCoreEngine:
    def __init__(self):
        self.output_callback = None
        self.ollama_manager = None
        self.analysis_data_path = None
        self.update_scan_status = None
        self.range_callback = None

        self.trace_normal = None
        self.trace_slow = None
        self.target_package = None
        self.analysis_data = None

        self.data_parser = FusionCoreDataParser()

        self.scanner = None
        self.scan_type = None

    def start(self, ollama_manager, output_callback, update_scan_status, range_callback=None):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.update_scan_status = update_scan_status
        self.range_callback = range_callback

    def load(self, trace_normal, trace_slow, target_package, analysis_data_path=None):
        self.trace_normal = trace_normal
        self.trace_slow = trace_slow
        self.target_package = target_package
        self.analysis_data_path = analysis_data_path
        
        self.scan_type = self.data_parser.get_scan_type(self.analysis_data_path)
        self.scanner = self._create_scanner(self.scan_type)
        if self.analysis_data_path:
            self.output_callback(f"🚀 Loading analysis data... {self.analysis_data_path}", True)
            self.analysis_data = self.data_parser.parse(self.analysis_data_path)
            self.output_callback(f"🚀 Loaded analysis data: {self.scan_type}, need to run {self.scanner.__class__.__name__}", True)
        else:
            self.scan_type = None

        self._update_scan_status(self.scan_type)
        self.scanner.start(self.trace_normal, self.trace_slow, self.target_package, self.ollama_manager, self.analysis_data, self.output_callback)

        if self.range_callback:
            self.range_callback(self.scanner.milestone_names)

    def run(self, output_callback=None, start_m_index=0, end_m_index=0):
        if output_callback:
            self.output_callback = output_callback
        if self.scanner:
            if hasattr(self.scanner, 'milestone_start_index'):
                self.scanner.milestone_start_index = start_m_index
            if hasattr(self.scanner, 'milestone_end_index'):
                self.scanner.milestone_end_index = end_m_index
        self.scanner.run(output_callback=output_callback)
 
    def stop(self):
        pass

    def _create_scanner(self, scan_type):
        if scan_type == "insight":
            return InsightScanner()
        return PointScanner()

    def _update_scan_status(self, scan_type):
        if scan_type == "point":
            self.update_scan_status("insight", checked=True)
        else:
            self.update_scan_status("point", checked=True)