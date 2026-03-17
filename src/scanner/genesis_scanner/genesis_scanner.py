from scanner.base_scanner import BaseScanner

class GenesisScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        pass

    def start(self, ollama_manager, output_callback):
        super().start(ollama_manager, output_callback)
        pass
    
    def run(self, trace_normal, trace_slow, target_package, analysis_data=None):
        super().run(trace_normal, trace_slow, target_package, analysis_data)
        pass

    def stop(self):
        pass