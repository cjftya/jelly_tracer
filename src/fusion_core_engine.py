import gc
import threading
from scanner.point_scanner.point_scanner import PointScanner
from scanner.point_scanner.point_scan_ui import PointScanUI
from scanner.insight_scanner.insight_scanner import InsightScanner
from analysis.fast_analysis import FastAnalysis
from analysis.deep_analysis import DeepAnalysis
from common_api import CommonAPI
from log import Logger

from scanner.insight_scanner.ai_data_generator import AIDataGenerator

class FusionCoreEngine:
    def __init__(self):
        self.output_callback = None
        self.llm_requester = None
        self.range_callback = None
        self.chart_canvas = None

        self.trace_normal = None
        self.trace_slow = None
        self.target_package = None

        self.point_scanner = PointScanner()
        self.point_scan_ui = PointScanUI()

        self.fast_analysis = FastAnalysis()
        self.deep_analysis = DeepAnalysis()
        self.mode = None

        self.selected_collected_data = None
        self.slice_list_widget = None
        self.selected_incidents_widget = None
        
        self.common_api = None

        # self.ai_data_generator = None

    def start(self, llm_requester, output_callback, range_callback=None, slice_list_widget=None, selected_incidents_widget=None):
        self.output_callback = output_callback
        self.llm_requester = llm_requester
        self.range_callback = range_callback
        self.slice_list_widget = slice_list_widget
        self.selected_incidents_widget = selected_incidents_widget

    def load(self, trace_normal, trace_slow, target_package, chart_canvas=None):
        self.chart_canvas = chart_canvas
        self.trace_normal = trace_normal
        self.trace_slow = trace_slow
        self.target_package = target_package
        self.common_api = CommonAPI(trace_normal, trace_slow, target_package)

        # test_data = [
        #     {'id': 316577, 'delay_ms': 204} , 
        #     {'id': 340565, 'delay_ms': 40} , 
        #     {'id': 329363, 'delay_ms': 100} , 
        #     {'id': 339598, 'delay_ms': 70} , 
        #     {'id': 328583, 'delay_ms': 54} , 
        #     {'id': 339419, 'delay_ms': 20} , 
        # ]
        # self.ai_data_generator = AIDataGenerator(self.common_api, test_data)
        
        self.point_scanner.start(self.common_api, self.target_package, self.llm_requester, self.output_callback)

        if self.range_callback:
            self.range_callback(self.point_scanner.milestone_names)

        # Draw data initialization
        if chart_canvas and self.point_scanner.milestones:
            self.point_scan_ui.set_info(self.point_scanner.milestones,
                                        self.point_scanner.milestone_marks)
        
        self.update_range_info()

        # Draw chart
        self.draw_ui(chart_canvas)
    
    def update_range_info(self):
        self.point_scanner.milestone_start_index = self.point_scan_ui.selected_start_index
        self.point_scanner.milestone_end_index = self.point_scan_ui.selected_end_index
        self.selected_collected_data = self.point_scanner.run(output_callback=self.output_callback)

        selected_incidents = []
        if self.selected_collected_data:
            selected_incidents = self.selected_collected_data["incidents"]

        if self.slice_list_widget:
            if len(selected_incidents) > 0:
                incidents_slice_info = [f"[{i['slice_id']}] {i['slice_name']} ({i['delay_delta_ms']})" for i in selected_incidents]
                self.slice_list_widget.configure(values=incidents_slice_info)
                self.slice_list_widget.set(incidents_slice_info[0])
            else:
                self.slice_list_widget.configure(values=["No incidents found"])
                self.slice_list_widget.set("No incidents found")

        if self.selected_incidents_widget:
            self.selected_incidents_widget.configure(values=["Selected Incidents"])
            self.selected_incidents_widget.set("Selected Incidents")

    def draw_ui(self, chart_canvas):
        if self.point_scanner.milestones and len(self.point_scanner.milestones) >= 2:
            if hasattr(chart_canvas, 'after'):
                chart_canvas.after(0, lambda: self.point_scan_ui.draw(chart_canvas, self.selected_collected_data))
            else:
                self.point_scan_ui.draw(chart_canvas, self.selected_collected_data)
                
        self.output_callback("Completed drawing chart UI")

    def on_chart_view_drag_start(self, event, chart_canvas):
        self.point_scan_ui.on_chart_view_drag_start(event, chart_canvas)

    def on_chart_view_drag(self, event, chart_canvas):
        self.point_scan_ui.on_chart_view_drag(event, chart_canvas)

    def on_chart_view_zoom(self, event, chart_canvas):
        self.point_scan_ui.on_chart_view_zoom(event, chart_canvas)

    def on_chart_view_resize(self, event, chart_canvas):
        self.point_scan_ui.on_chart_view_resize(event, chart_canvas)

    def on_find_incidents_clicked(self):
        self.update_range_info()
        if self.chart_canvas:
            self.draw_ui(self.chart_canvas)

    def on_selected_incident(self, choice):
        if self.selected_incidents_widget:
            if choice == "No incidents found":
                return
                
            current_values = list(self.selected_incidents_widget.cget("values"))
            
            if current_values == ["Selected Incidents"]:
                current_values = [choice]
            else:
                if choice not in current_values:
                    current_values.append(choice)
            
            self.selected_incidents_widget.configure(values=current_values)
            self.selected_incidents_widget.set(choice)

    def run(self, output_callback=None, mode=None):
        if output_callback:
            self.output_callback = output_callback
        
        self.mode = mode
        if self.is_fast_analysis():
            self.fast_analysis.start(self.common_api, self.target_package, self.llm_requester, self.output_callback)
        elif self.is_deep_analysis():
            self.deep_analysis.start(self.common_api, self.target_package, self.llm_requester, self.output_callback)

        if self.selected_collected_data is None:
            self.output_callback("⚠️ [Error] Collected data is missing. Cannot proceed.", True)
            return

        # Logger.log(self.selected_collected_data)
        current_values = list(self.selected_incidents_widget.cget("values"))
        if current_values == ["Selected Incidents"]:
            self.output_callback("⚠️ [Error] No incidents selected. Cannot proceed.", True)
            return
        
        incident_map = {inc["slice_id"]: inc for inc in self.selected_collected_data["incidents"]}
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
        
        cumstomize_incidents = self.selected_collected_data.copy()
        cumstomize_incidents["incidents"] = selected_incidents
        cumstomize_incidents["overall_timeline_context"] = overall_timeline_context
        if self.is_fast_analysis():
            self.fast_analysis.run(cumstomize_incidents, output_callback=output_callback)
        elif self.is_deep_analysis():
            self.deep_analysis.run(cumstomize_incidents, output_callback=output_callback)
        
    def on_question_to_ai(self, text):
        if not self.llm_requester or not self.output_callback:
            return
            
        def ask():
            try:
                self.output_callback(f"\n🧐 Question: {text}")
                if self.is_fast_analysis():
                    ai_context = self.fast_analysis.ai_ask_system_context
                elif self.is_deep_analysis():
                    ai_context = self.deep_analysis.ai_ask_system_context
                ai_context.append({
                    "role": "user", 
                    "content": f"[QUESTION] 이건 나의 질문이야. 데이터를 보고 상세히 답해줘. 답변은 꼭 한국어로 작성해줘.\n{text}"
                })

                raw_res = self.llm_requester.request(
                    context=ai_context, 
                    chunk_callback=lambda chunk: self.llm_requester.chunk_callback(chunk, self.output_callback)
                )
                full_content = raw_res.get("message", {}).get("content", "")
                self.output_callback(f"\n✨ AI:\n{full_content}")
            except Exception as e:
                self.output_callback(f"\n⚠️ AI failed: {str(e)}", True)
                
        threading.Thread(target=ask, daemon=True).start()

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