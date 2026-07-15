from typing import Optional

from application.fusion_core_engine import FusionCoreEngine
from llm_client.llm_requester import LLMRequester
from server.trace_server_manager import TraceServerManager


class Engine:
    def __init__(self, window=None):
        self.window = window
        self.llm_requester: Optional[LLMRequester] = None
        self.server_manager: Optional[TraceServerManager] = None
        # ================
        self.fusion_core_engine = FusionCoreEngine()

    def start(
        self,
        log_callback=None,
        range_callback=None,
        on_slices_ready=None,
        on_selected_incidents_ready=None,
        milestone_targets=None,
    ):
        if self.llm_requester is None:
            self.llm_requester = LLMRequester()
        if self.server_manager is None:
            self.server_manager = TraceServerManager()
        # =====================

        self.fusion_core_engine.start(
            self.llm_requester,
            log_callback,
            range_callback=range_callback,
            on_slices_ready=on_slices_ready,
            on_selected_incidents_ready=on_selected_incidents_ready,
            milestone_targets=milestone_targets,
        )

    def stop(self):
        if self.llm_requester:
            self.llm_requester.stop_engine()
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

        self.llm_requester.init_client(client_type, api_key)
        self.llm_requester.start_engine()

        if not self.server_manager:
            self.server_manager = TraceServerManager()

        self.server_manager.stop_servers()
        self.server_manager.start_servers(trace_normal, trace_slow)

        self.fusion_core_engine.load(
            trace_normal, trace_slow, target_package, chart_canvas=chart_canvas
        )

    def on_selected_incident(self, choice):
        self.fusion_core_engine.on_selected_incident(choice)

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

    def run(self, mode="Fast Analysis"):
        self.fusion_core_engine.run(mode=mode)
