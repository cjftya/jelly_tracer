import gc

from application.event_poster import EventPoster
from core.analysis_context import AnalysisContext
from core.analysis.deep_analysis import DeepAnalysis
from core.analysis.fast_analysis import FastAnalysis
from core.common_api import CommonAPI
from core.scanner.point_scanner.point_scanner import PointScanner
from ui.point_scan_view import PointScanView


class FusionCoreEngine:
    def __init__(self):
        self.event_poster = EventPoster()
        self.llm_requester = None
        self.range_callback = None
        self.chart_canvas = None

        self.trace_normal = None
        self.trace_slow = None
        self.target_package = None

        self.point_scanner = PointScanner()
        self.point_scan_view = PointScanView()

        self.fast_analysis = FastAnalysis()
        self.deep_analysis = DeepAnalysis()
        self.mode = None

        self.selected_collected_data = None
        self.on_slices_ready = None
        self.on_selected_incidents_ready = None
        self.selected_incidents_list = []
        self.milestone_targets = None

        self.common_api = None
        self.analysis_context: AnalysisContext | None = None

    def start(
        self,
        llm_requester,
        log_callback,
        range_callback=None,
        on_slices_ready=None,
        on_selected_incidents_ready=None,
        milestone_targets=None,
    ):
        self.event_poster.set_log_handler(log_callback)
        self.llm_requester = llm_requester
        self.range_callback = range_callback
        self.on_slices_ready = on_slices_ready
        self.on_selected_incidents_ready = on_selected_incidents_ready
        self.milestone_targets = milestone_targets

    def load(self, trace_normal, trace_slow, target_package, chart_canvas=None):
        self.chart_canvas = chart_canvas
        self.trace_normal = trace_normal
        self.trace_slow = trace_slow
        self.target_package = target_package
        self.common_api = CommonAPI(trace_normal, trace_slow, target_package)
        self.analysis_context = AnalysisContext(
            common_api=self.common_api,
            target_package=target_package,
            llm_requester=self.llm_requester,
            event_poster=self.event_poster,
        )

        self.point_scanner.start(
            self.analysis_context, self.milestone_targets
        )

        if self.range_callback:
            self.range_callback(self.point_scanner.milestone_names)

        # Draw data initialization
        if chart_canvas and self.point_scanner.milestones:
            self.point_scan_view.set_info(
                self.point_scanner.milestones, self.point_scanner.milestone_marks
            )

        self.update_range_info()

        # Draw chart
        self.draw_ui(chart_canvas)

    def update_range_info(self):
        self.point_scanner.milestone_start_index = (
            self.point_scan_view.selected_start_index
        )
        self.point_scanner.milestone_end_index = self.point_scan_view.selected_end_index
        self.selected_collected_data = self.point_scanner.run()

        selected_incidents = []
        if self.selected_collected_data:
            selected_incidents = self.selected_collected_data["incidents"]

        if self.on_slices_ready:
            if len(selected_incidents) > 0:
                incidents_slice_info = [
                    f"[{i['slice_id']}] {i['slice_name']} ({i['delay_delta_ms']})"
                    for i in selected_incidents
                ]
                self.on_slices_ready(incidents_slice_info)
            else:
                self.on_slices_ready(["No incidents found"])

        self.selected_incidents_list = ["Selected Incidents"]
        if self.on_selected_incidents_ready:
            self.on_selected_incidents_ready(
                self.selected_incidents_list, "Selected Incidents"
            )

    def draw_ui(self, chart_canvas):
        if self.point_scanner.milestones and len(self.point_scanner.milestones) >= 2:
            if hasattr(chart_canvas, "after"):
                chart_canvas.after(
                    0,
                    lambda: self.point_scan_view.draw(
                        chart_canvas, self.selected_collected_data
                    ),
                )
            else:
                self.point_scan_view.draw(chart_canvas, self.selected_collected_data)

        self.event_poster.log("Completed drawing chart UI")

    def on_chart_view_drag_start(self, event, chart_canvas):
        self.point_scan_view.on_chart_view_drag_start(event, chart_canvas)

    def on_chart_view_drag(self, event, chart_canvas):
        self.point_scan_view.on_chart_view_drag(event, chart_canvas)

    def on_chart_view_zoom(self, event, chart_canvas):
        self.point_scan_view.on_chart_view_zoom(event, chart_canvas)

    def on_chart_view_resize(self, event, chart_canvas):
        self.point_scan_view.on_chart_view_resize(event, chart_canvas)

    def on_find_incidents_clicked(self):
        self.update_range_info()
        if self.chart_canvas:
            self.draw_ui(self.chart_canvas)

    def on_selected_incident(self, choice):
        if choice == "No incidents found":
            return

        if (
            self.selected_incidents_list == ["Selected Incidents"]
            or not self.selected_incidents_list
        ):
            current_values = [choice]
        else:
            current_values = self.selected_incidents_list.copy()
            if choice not in current_values:
                current_values.append(choice)

        self.selected_incidents_list = current_values
        if self.on_selected_incidents_ready:
            self.on_selected_incidents_ready(self.selected_incidents_list, choice)

    def run(self, mode=None):
        if self.analysis_context is None:
            self.event_poster.log(
                "⚠️ [Error] Collected data is missing. Cannot proceed.", True
            )
            return

        self.mode = mode
        if self.is_fast_analysis():
            self.fast_analysis.start(self.analysis_context)
        elif self.is_deep_analysis():
            self.deep_analysis.start(self.analysis_context)

        if self.selected_collected_data is None:
            self.event_poster.log(
                "⚠️ [Error] Collected data is missing. Cannot proceed.", True
            )
            return

        if not self.selected_incidents_list or self.selected_incidents_list == [
            "Selected Incidents"
        ]:
            self.event_poster.log(
                "⚠️ [Error] No incidents selected. Cannot proceed.", True
            )
            return

        current_values = self.selected_incidents_list
        if current_values == ["Selected Incidents"]:
            self.event_poster.log(
                "⚠️ [Error] No incidents selected. Cannot proceed.", True
            )
            return

        incident_map = {
            inc["slice_id"]: inc for inc in self.selected_collected_data["incidents"]
        }
        selected_incidents = []
        for val in current_values:
            if val.startswith("[") and "]" in val:
                try:
                    slice_id_str = val[1 : val.find("]")]
                    slice_id = int(slice_id_str)
                    if slice_id in incident_map:
                        selected_incidents.append(incident_map[slice_id])
                except (ValueError, IndexError):
                    continue

        overall_timeline_context = []
        for inc in self.selected_collected_data["incidents"]:
            col = {}
            col["slice_id"] = int(inc["slice_id"])
            col["slice_name"] = inc["slice_name"]
            col["thread_name"] = inc.get("thread_name", "Unknown")

            start_ms = inc["start_timestamp"] / 1000000.0
            dur_ms = inc["duration_ns"] / 1000000.0

            col["start_ms"] = round(start_ms, 2)
            col["dur_ms"] = round(dur_ms, 2)
            col["end_ms"] = round(start_ms + dur_ms, 2)

            overall_timeline_context.append(col)

        customize_incidents = self.selected_collected_data.copy()
        customize_incidents["incidents"] = selected_incidents
        customize_incidents["overall_timeline_context"] = overall_timeline_context
        if self.is_fast_analysis():
            self.fast_analysis.run(customize_incidents)
        elif self.is_deep_analysis():
            self.deep_analysis.run(customize_incidents)

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
