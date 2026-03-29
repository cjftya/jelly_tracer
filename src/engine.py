from fusion_core_engine import FusionCoreEngine
from trace_server_manager import TraceServerManager
from llm_requester import LLMRequester

class Engine:
    def __init__(self, gui=None):
        self.gui = gui
        self.llm_requester = None
        self.server_manager = None
        self.output_callback = None
        #================
        self.fusion_core_engine = FusionCoreEngine()

    def start(self, output_callback=None, range_callback=None):
        self.output_callback = output_callback
        if self.llm_requester is None:
            self.llm_requester = LLMRequester()
        if self.server_manager is None:
            self.server_manager = TraceServerManager()
        #=====================

        self.fusion_core_engine.start(
            self.llm_requester, 
            self.output_callback, 
            range_callback=range_callback
        )

    def stop(self):
        if self.llm_requester:
            self.llm_requester.stop_engine()
            self.llm_requester = None
        if self.server_manager:
            self.server_manager.stop_servers()
            self.server_manager = None
        #=====================
        self.fusion_core_engine.stop()

    def load(self, trace_normal, trace_slow, target_package, model_name=None, mode="Fast Analysis", client_type=None, api_key=None):
        if client_type:
            self.llm_requester.set_client(client_type)
        if model_name:
            self.llm_requester.set_model_name(model_name)
        if api_key:
            self.llm_requester.set_api_key(api_key)
        
        self.server_manager.stop_servers()
        self.server_manager.start_servers(trace_normal, trace_slow)

        self.llm_requester.start_engine()

        self.fusion_core_engine.load(trace_normal, trace_slow, target_package, mode=mode)

    def run(self, output_callback=None, start_m_index=0, end_m_index=0):
        self.fusion_core_engine.run(
            output_callback=output_callback,
            start_m_index=start_m_index,
            end_m_index=end_m_index
        )