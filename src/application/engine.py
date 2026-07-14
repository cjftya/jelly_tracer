from typing import Optional

from application.fusion_core_engine import FusionCoreEngine
from llm_client.llm_requester import LLMRequester
from server.trace_server_manager import TraceServerManager


class Engine:
    def __init__(self, gui=None):
        self.gui = gui
        self.llm_requester: Optional[LLMRequester] = None
        self.server_manager: Optional[TraceServerManager] = None
        self.output_callback = None
        # ================
        self.fusion_core_engine = FusionCoreEngine()

    def start(
        self,
        output_callback=None,
        range_callback=None,
        on_slices_ready=None,
        on_selected_incidents_ready=None,
        milestone_targets=None,
    ):
        self.output_callback = output_callback
        if self.llm_requester is None:
            self.llm_requester = LLMRequester()
            self.llm_requester.start_engine(full=True)
        if self.server_manager is None:
            self.server_manager = TraceServerManager()
        # =====================

        self.fusion_core_engine.start(
            self.llm_requester,
            self.output_callback,
            range_callback=range_callback,
            on_slices_ready=on_slices_ready,
            on_selected_incidents_ready=on_selected_incidents_ready,
            milestone_targets=milestone_targets,
        )

    def on_selected_incident(self, choice):
        self.fusion_core_engine.on_selected_incident(choice)

    def stop(self):
        if self.llm_requester:
            self.llm_requester.stop_engine(full=True)
            self.llm_requester = None
        if self.server_manager:
            self.server_manager.stop_servers()
            self.server_manager = None
        # =====================
        self.fusion_core_engine.stop()

    def load(
        self,
        trace_normal,
        trace_slow,
        target_package,
        client_type=None,
        api_key=None,
        chart_canvas=None,
    ):
        if not self.llm_requester:
            self.llm_requester = LLMRequester()
            self.llm_requester.start_engine(full=True)

        if client_type:
            self.llm_requester.init_client(client_type)
        if api_key:
            self.llm_requester.set_api_key(api_key)

        if not self.server_manager:
            self.server_manager = TraceServerManager()

        self.server_manager.stop_servers()
        self.server_manager.start_servers(trace_normal, trace_slow)

        self.fusion_core_engine.load(
            trace_normal, trace_slow, target_package, chart_canvas=chart_canvas
        )

    def on_chart_view_drag_start(self, event, chart_canvas):
        self.fusion_core_engine.on_chart_view_drag_start(event, chart_canvas)

    def on_chart_view_drag(self, event, chart_canvas):
        self.fusion_core_engine.on_chart_view_drag(event, chart_canvas)

    def on_chart_view_zoom(self, event, chart_canvas):
        self.fusion_core_engine.on_chart_view_zoom(event, chart_canvas)

    def on_chart_view_resize(self, event, chart_canvas):
        self.fusion_core_engine.on_chart_view_resize(event, chart_canvas)

    def on_find_incidents_clicked(self):
        self.fusion_core_engine.on_find_incidents_clicked()

    def run(self, output_callback=None, model_name=None, mode="Fast Analysis"):
        if not self.llm_requester:
            self.llm_requester = LLMRequester()
            self.llm_requester.start_engine(full=True)

        if model_name:
            self.llm_requester.set_model_name(model_name)

        self.fusion_core_engine.run(output_callback=output_callback, mode=mode)
