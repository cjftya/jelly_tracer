import json

from core.scanner.insight_scanner.insight_scan_prompt_values import (
    InsightScanPromptValues,
)
from core.scanner.insight_scanner.insight_scanner import InsightScanner


class FastAnalysis:
    def __init__(self):
        self.insight_scanner = InsightScanner()

    def start(self, common_api, target_package, llm_requester, event_poster):
        self.insight_scanner.start(
            common_api, target_package, llm_requester, event_poster
        )

    def run(self, collected_data, event_poster):
        incidents = collected_data.get("incidents", [])
        if incidents:
            primary_incident = incidents[0]
            primary_incident_data = {}
            primary_incident_data["target_id"] = primary_incident.get("slice_id")
            primary_incident_data["start_ts_ns"] = int(
                primary_incident.get("start_timestamp", 0)
            )
            primary_incident_data["duration_ns"] = int(
                primary_incident.get("duration_ns", 0)
            )
            primary_incident_data["milestones"] = collected_data.get(
                "milestone_info", None
            )
            primary_incident_data["normal_baseline"] = collected_data.get(
                "normal_baseline", None
            )
            primary_incident_data["overall_timeline_context"] = collected_data.get(
                "overall_timeline_context", None
            )
            primary_incident_data["fact_only"] = False

            self.insight_scanner.collected_data = primary_incident_data
            final_result = self.insight_scanner.run()

            if final_result:
                summary_context = final_result[0]
                final_report = final_result[1]
                thinking_text = final_result[2]

                event_poster.log(f"\n🧠 [AI Thinking...]\n{thinking_text}\n")
                event_poster.log(final_report)

    def stop(self):
        self.insight_scanner.stop()
