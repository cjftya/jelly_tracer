import datetime
import json
import re
from typing import Optional

from core.analysis_context import AnalysisContext
from core.scanner.insight_scanner.insight_scanner import InsightScanner


class DeepAnalysis:
    def __init__(self):
        self.insight_scanner = InsightScanner()
        self.context: Optional[AnalysisContext] = None

        self.system_prompt_template = """
# [Role]
You are the "Chief Android System Performance Forensic Inspector". 
Your mission is to synthesize the selected incident reports into a "Supreme Verdict" that explains the systemic root cause of the entire milestone delay.

# [CRITICAL DIRECTIVE: SYSTEMIC SYNTHESIS]
- **Focus on Patterns**: Instead of finding one ID, identify recurring bottlenecks, wchan states, or origin_hints across the selected incidents.
- **Explain the "Why"**: Connect the metadata ratios (App% vs System%) to the collective evidence found in the 3 cases.
- **Chain of Events**: Describe how the selected incidents might be linked (e.g., one case's I/O load affecting another case's scheduling).

# [Investigation Protocol: Deep-Scan CoT]
You MUST strictly follow this logical flow inside [[THOUGHT]] tags:
1. **[Holistic Review]**: Review all provided cases. Identify the dominant physical stats (io, mutex, cpu).
2. **[Pattern Matching]**: Find "Common Enemies" (e.g., recurring UFS Driver stalls or Lock contentions).
3. **[Ratio Validation]**: How do the provided cases collectively justify the 'calculated_ratios' (App vs System) provided in the metadata?
4. **[Causality Synthesis]**: Construct a unified technical theory explaining the milestone's overall performance degradation.

# [Output Requirements: Hybrid Code-Switching]
1. **⚖️ [Supreme Verdict]**: 
   - A high-impact summary (3-4 sentences) defining the core systemic bottleneck of the milestone in Hybrid style.
2. **🕵️ [Systemic Pattern Analysis]**: 
   - Describe the recurring technical patterns found across the selected incidents.
   - Link 'wchan' and 'MRI stats' from the 'flat_tree' to the overall system state.
3. **📉 [Evidence Correlation Matrix]**: 
   - Briefly summarize how each provided case contributes to the total delay.
4. **🎯 [Technical Verdict & Ratio Justification]**: 
   - Finalize the reasoning behind the [App% : System%] ratios based on the aggregated forensic evidence.

# [Strict Warning]
- **NO Target-ID Required**: Focus on the holistic explanation of the 3 cases.
- **Language**: Korean Grammar + English Technical Terms.
- **Fact-Only**: Use only the provided metadata and incident data.
        """

    def start(self, context: AnalysisContext):
        self.context = context
        self.insight_scanner.start(context)

    def _require_context(self) -> AnalysisContext:
        if self.context is None:
            raise RuntimeError("Analysis context has not been initialized.")
        return self.context

    def stop(self):
        self.insight_scanner.stop()
        self.context = None

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
        milestone_context = collected_data.get("milestone_info")
        if not isinstance(incidents, (list, tuple)) or not incidents:
            event_poster.log(
                "⚠️ [Error] No incidents are available for deep analysis.", True
            )
            return None
        if (
            not isinstance(milestone_context, dict)
            or not {"start_name", "end_name", "total_delay_ms"}.issubset(
                milestone_context
            )
        ):
            event_poster.log(
                "⚠️ [Error] Milestone data is incomplete. Cannot proceed.", True
            )
            return None

        try:
            milestone_context = dict(milestone_context)
            milestone_context["total_delay_ms"] = float(
                milestone_context["total_delay_ms"]
            )
        except (TypeError, ValueError):
            event_poster.log(
                "⚠️ [Error] Milestone delay data is invalid. Cannot proceed.", True
            )
            return None

        captured_delay_ms = collected_data.get("captured_delay_ms", 0)
        overlap_factor = collected_data.get("overlap_factor", 0)
        coverage_efficiency = collected_data.get("coverage_efficiency", 0)
        concurrency_mode = collected_data.get("concurrency_mode", 0)
        overall_timeline_context = collected_data.get("overall_timeline_context", {})
        incidents_result_data = []

        for idx, incident in enumerate(incidents[:3]):
            if not isinstance(incident, dict) or incident.get("is_ghost_incident"):
                continue

            try:
                target_id = int(incident["slice_id"])
                start_ts_ns = int(incident["start_timestamp"])
                duration_ns = int(incident["duration_ns"])
            except (KeyError, TypeError, ValueError):
                event_poster.log(
                    "⚠️ [Error] Skipping incident with invalid timing data.", True
                )
                continue

            if target_id <= 0 or start_ts_ns < 0 or duration_ns <= 0:
                event_poster.log(
                    "⚠️ [Error] Skipping incident with out-of-range timing data.", True
                )
                continue

            primary_incident_data = {
                "target_id": target_id,
                "start_ts_ns": start_ts_ns,
                "duration_ns": duration_ns,
                "milestones": milestone_context,
                "normal_baseline": collected_data.get("normal_baseline"),
                "fact_only": True,
                "overall_timeline_context": overall_timeline_context,
            }

            self.insight_scanner.collected_data = primary_incident_data
            final_result = self.insight_scanner.run()

            if not final_result:
                continue
            summary_context = final_result[0]
            ai_analyst_text = final_result[3]
            flat_tree = summary_context.get("prime_suspects_flat", [])

            if not flat_tree:
                continue
            root = flat_tree[0]

            incident_meta = {
                "delta_time": root.get("delta_time", 0),
                "self_time": root.get("self_time", 0),
                "wait_time": root.get("wait_time", 0),
                "mri_stats": root.get("physical_stats", {}),
            }

            incidents_result_data.append(
                {
                    "set_no": idx + 1,
                    "case_name": incident.get("slice_name"),
                    "ai_summary": ai_analyst_text,
                    "incident_meta": incident_meta,
                    "flat_tree": flat_tree,
                }
            )

        if not incidents_result_data:
            event_poster.log(
                "⚠️ [Error] No incidents could be analyzed for deep analysis.", True
            )
            return None

        range_name = f"{milestone_context['start_name']} ~ {milestone_context['end_name']}"
        request_context = {
            "metadata": {
                "app_name": self.context.target_package,
                "milestone_range": range_name,
                "total_delay_delta_ms": round(milestone_context["total_delay_ms"], 1),
                "investigation_date": datetime.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "captured_delay_ms": captured_delay_ms,
                "coverage_efficiency": coverage_efficiency,
                "overlap_factor": overlap_factor,
                "concurrency_mode": concurrency_mode,
            },
            "incidents": incidents_result_data,
            "global_timeline_summary": overall_timeline_context,
        }

        ai_context = [
            {"role": "system", "content": self.system_prompt_template},
            {
                "role": "user",
                "content": json.dumps(request_context, indent=2, ensure_ascii=False),
            },
        ]
        full_response_text = self.request_analysis(ai_context)
        if not full_response_text:
            return None

        anchor_match = re.search(r"Supreme\s+Verdict", full_response_text, re.IGNORECASE)
        if anchor_match:
            anchor_idx = anchor_match.start()
            line_start_idx = full_response_text.rfind("\n", 0, anchor_idx) + 1
            raw_thought = full_response_text[:line_start_idx].strip()
            final_summary = full_response_text[line_start_idx:].strip()
            ai_thought = re.sub(
                r"\[{1,2}/?THOUGHT\]{1,2}", "", raw_thought, flags=re.IGNORECASE
            ).strip()
            if not ai_thought:
                ai_thought = "None"
        else:
            ai_thought = "None"
            final_summary = full_response_text.strip()

        event_poster.log(f"\n🧠 [AI Thinking...]\n{ai_thought}\n")

        investigation_report = {
            "milestone_context": milestone_context,
            "final_ai_summary": final_summary,
            "raw_data": incidents_result_data,
        }
        return self.generate_final_report(investigation_report)

    def request_analysis(self, context):
        analysis_context = self._require_context()
        event_poster = analysis_context.event_poster
        llm = analysis_context.llm_requester
        if not llm:
            event_poster.log("⚠️ [Error] LLM requester is missing.", True)
            return ""
        raw_res = llm.request(
            context=context,
            options=llm.get_insight_scan_option(),
            chunk_callback=lambda chunk: llm.chunk_callback(chunk, event_poster),
        )
        if not isinstance(raw_res, dict) or raw_res.get("error"):
            error_message = (
                raw_res.get("error", "Invalid LLM response")
                if isinstance(raw_res, dict)
                else "Invalid LLM response"
            )
            event_poster.log(f"⚠️ AI Analysis failed: {error_message}", True)
            return ""

        total_tokens = raw_res.get("prompt_eval_count", 0) + raw_res.get(
            "eval_count", 0
        )
        event_poster.log(f"\n\\token {total_tokens}")
        return raw_res.get("message", {}).get("content", "")

    def generate_final_report(self, investigation_report):
        milestone_context = investigation_report["milestone_context"]
        report_text = investigation_report["final_ai_summary"]
        raw_data = investigation_report["raw_data"]

        range_name = (
            f"{milestone_context['start_name']} ~ {milestone_context['end_name']}"
        )
        total_delay = milestone_context.get("total_delay_ms", 0)

        progress_val = min(int(total_delay / 20), 5)
        progress_bar = "■" * progress_val + "□" * (5 - progress_val)

        case_list_str = ""
        for case in raw_data:
            m = case["incident_meta"]
            case_list_str += f"  • Case {case['set_no']}: {case['case_name']} ({m['delta_time']}ms)\n"
            case_list_str += (
                f"    └─ [Self: {m['self_time']}ms | Wait: {m['wait_time']}ms]\n"
            )

        final_report = f"""
───────────────────────────────────────
📑 [ PERFORMANCE ANALYSIS REPORT : DEEP-SCAN ]

ℹ️ [ CASE METADATA ]
  • 🗓️ Timeline : {range_name}
  • ⏱️ Duration : {total_delay:,.1f} ms (Total Delta)
  • 🎯 Target   : {self._require_context().target_package}
  • ⚡ Impact   : {progress_bar}

🧠 [ AI SUPREME VERDICT & ANALYSIS ]
{report_text}

📂 [ INVESTIGATION EVIDENCE ]
{case_list_str.rstrip()}

───────────────────────────────────────
"""
        if self._require_context().event_poster:
            self._require_context().event_poster.log(final_report)
        return final_report
