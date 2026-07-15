from core.analysis_context import AnalysisContext
from core.scanner.insight_scanner.insight_scanner import InsightScanner


class FastAnalysis:
    def __init__(self):
        self.context = None
        self.insight_scanner = InsightScanner()

    def start(self, context: AnalysisContext) -> None:
        self.context = context
        self.insight_scanner.start(context)

    def run(self, collected_data):
        if self.context is None:
            return None

        event_poster = self.context.event_poster
        if not isinstance(collected_data, dict):
            event_poster.log(
                "⚠️ [Error] Invalid incident data. Cannot proceed.", True
            )
            return None

        incidents = collected_data.get("incidents", [])
        if not isinstance(incidents, (list, tuple)) or not incidents:
            event_poster.log(
                "⚠️ [Error] No incidents are available for fast analysis.", True
            )
            return None

        primary_incident = incidents[0]
        milestone_info = collected_data.get("milestone_info")
        if (
            not isinstance(primary_incident, dict)
            or not isinstance(milestone_info, dict)
            or not {"start_name", "end_name", "total_delay_ms"}.issubset(
                milestone_info
            )
        ):
            event_poster.log(
                "⚠️ [Error] Incident or milestone data is incomplete.", True
            )
            return None

        try:
            target_id = int(primary_incident["slice_id"])
            start_ts_ns = int(primary_incident["start_timestamp"])
            duration_ns = int(primary_incident["duration_ns"])
        except (KeyError, TypeError, ValueError):
            event_poster.log(
                "⚠️ [Error] Incident timing data is invalid.", True
            )
            return None

        if target_id <= 0 or start_ts_ns < 0 or duration_ns <= 0:
            event_poster.log(
                "⚠️ [Error] Incident timing data is out of range.", True
            )
            return None

        primary_incident_data = {
            "target_id": target_id,
            "start_ts_ns": start_ts_ns,
            "duration_ns": duration_ns,
            "milestones": milestone_info,
            "normal_baseline": collected_data.get("normal_baseline"),
            "overall_timeline_context": collected_data.get(
                "overall_timeline_context"
            ),
            "fact_only": False,
        }

        self.insight_scanner.collected_data = primary_incident_data
        final_result = self.insight_scanner.run()

        if final_result:
            _, final_report, thinking_text, _ = final_result
            event_poster.log(f"\n🧠 [AI Thinking...]\n{thinking_text}\n")
            event_poster.log(final_report)

        return final_result

    def stop(self):
        self.insight_scanner.stop()
        self.context = None
