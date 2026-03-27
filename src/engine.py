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

    def start(self, output_callback=None, range_callback=None):
        self.output_callback = output_callback
        if self.ollamaManager is None:
            self.ollamaManager = OllamaManager()
            self.ollamaManager.start_engine()
        if self.server_manager is None:
            self.server_manager = TraceServerManager()
        #=====================
        self.fusion_core_engine.start(
            self.ollamaManager, 
            self.output_callback, 
            range_callback=range_callback
        )

    def stop(self):
        if self.ollamaManager:
            self.ollamaManager.stop_engine()
            self.ollamaManager = None
        if self.server_manager:
            self.server_manager.stop_servers()
            self.server_manager = None
        #=====================
        self.fusion_core_engine.stop()

    def load(self, trace_normal, trace_slow, target_package, model_name=None):
        if model_name:
            self.ollamaManager.set_model_name(model_name)
        
        self.server_manager.stop_servers()
        self.server_manager.start_servers(trace_normal, trace_slow)

        self.fusion_core_engine.load(trace_normal, trace_slow, target_package)

    def run(self, output_callback=None, start_m_index=0, end_m_index=0):
        self.fusion_core_engine.run(
            output_callback=output_callback,
            start_m_index=start_m_index,
            end_m_index=end_m_index
        )