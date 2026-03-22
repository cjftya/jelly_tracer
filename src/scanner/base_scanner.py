from fusion_core_data_collector import FusionCoreDataCollector

class BaseScanner:
    def __init__(self):
        self.output_callback = None
        self.ollama_manager = None
        self.target_package = None
        self.data_collector = FusionCoreDataCollector()
        self.analysis_data = None

    def start(self, trace_normal, trace_slow, target_package, ollama_manager, analysis_data, output_callback):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.analysis_data = analysis_data

    def run(self, output_callback=None):
        if output_callback:
            self.output_callback = output_callback