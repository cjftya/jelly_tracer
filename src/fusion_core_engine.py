from scanner.base_scanner import BaseScanner
from scanner.point_scanner.point_scanner import PointScanner
from scanner.insight_scanner.insight_scanner import InsightScanner
from fusion_core_data_parser import FusionCoreDataParser

class FusionCoreEngine:
    def __init__(self):
        self.output_callback = None
        self.ollama_manager = None
        self.analysis_data_path = None
        self.data_parser = FusionCoreDataParser()

        self.scanner = None
        self.scan_type = None

    def start(self, ollama_manager, output_callback, update_scan_status):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.update_scan_status = update_scan_status

    def run(self, trace_normal, trace_slow, target_package, analysis_data_path=None):
        self.analysis_data_path = analysis_data_path
        
        self.scan_type = self.data_parser.get_scan_type(self.analysis_data_path)
        self.scanner = self._create_scanner(self.scan_type)
        analysis_data = None
        if self.analysis_data_path:
            self.output_callback(f"🚀 Loading analysis data... {self.analysis_data_path}", True)
            analysis_data = self.data_parser.parse(self.analysis_data_path)
            self.output_callback(f"🚀 Loaded analysis data: {self.scan_type}, need to run {self.scanner.__class__.__name__}", True)
        else:
            self.scan_type = "point"
            analysis_data = None

        self._update_scan_status(self.scan_type)
        self.scanner.start(self.ollama_manager, self.output_callback)
        self.scanner.run(trace_normal, trace_slow, target_package, analysis_data)
 
    def stop(self):
        pass

    def _create_scanner(self, scan_type):
        if scan_type == "point":
            return InsightScanner()
        return PointScanner()

    def _update_scan_status(self, scan_type):
        if scan_type == "point":
            self.update_scan_status("insight", checked=True)
        else:
            self.update_scan_status("point", checked=True)