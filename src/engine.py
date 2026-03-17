from fusion_core_engine import FusionCoreEngine
from ollama_manager import OllamaManager
from trace_server_manager import TraceServerManager

class Engine:
    def __init__(self, gui=None):
        self.gui = gui
        self.ollamaManager = None
        self.server_manager = None
        self.output_callback = None
        #================
        self.fusion_core_engine = FusionCoreEngine()

    def update_scan_status(self, scan_type, checked=None, enabled=None):
        if self.gui:
            self.gui.set_scan_checkbox_state(scan_type, checked, enabled)

    def start(self, output_callback=None):
        self.output_callback = output_callback
        if self.ollamaManager is None:
            self.ollamaManager = OllamaManager()
            self.ollamaManager.start_engine()
        if self.server_manager is None:
            self.server_manager = TraceServerManager()
        #=====================
        self.fusion_core_engine.start(self.ollamaManager, self.output_callback, self.update_scan_status)

    def stop(self):
        if self.ollamaManager:
            self.ollamaManager.stop_engine()
        if self.server_manager:
            self.server_manager.stop_servers()
        #=====================
        self.fusion_core_engine.stop()

    def run(self, trace_normal, trace_slow, target_package, model_name=None, analysis_data_path=None):
        if model_name:
            self.ollamaManager.set_model_name(model_name)
        self.server_manager.stop_servers()
        self.server_manager.start_servers(trace_normal, trace_slow)
        #========================
        self.fusion_core_engine.run(trace_normal, trace_slow, target_package, analysis_data_path=analysis_data_path)