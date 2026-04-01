from scanner.insight_scanner.insight_scanner import InsightScanner
from log import Logger

class FastAnalysis:
    def __init__(self):
        self.insight_scanner = InsightScanner()

    def start(self, common_api, target_package, ollama_manager, output_callback):
        self.insight_scanner.start(common_api, target_package, ollama_manager, output_callback)

    def run(self, collected_data, output_callback):
        incidents = collected_data.get("incidents", [])
        if incidents:
            primary_incident = incidents[0] 
            primary_incident_data = {}
            primary_incident_data["target_id"] = primary_incident.get("slice_id")
            primary_incident_data["start_ts_ns"] = int(primary_incident.get("start_timestamp", 0))
            primary_incident_data["duration_ns"] = int(primary_incident.get("duration_ns", 0))
            primary_incident_data["milestones"] = collected_data.get("milestone_info", None)
            primary_incident_data["normal_baseline"] = collected_data.get("normal_baseline", None)
            primary_incident_data["fact_only"] = False

            self.insight_scanner.collected_data = primary_incident_data
            final_result = self.insight_scanner.run(output_callback=output_callback)

            if final_result:
                summary_context = final_result[0]
                final_report = final_result[1]
                thinking_text = final_result[2]

                output_callback(f"\n🧠 [AI Thinking...]\n{thinking_text}\n")
                output_callback(final_report)

    def stop(self):
        self.insight_scanner.stop()