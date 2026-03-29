import re
import datetime
import json
from scanner.insight_scanner.insight_scanner import InsightScanner
from log import Logger

class DeepAnalysis:
    def __init__(self):
        self.insight_scanner = InsightScanner()
        self.target_package = None
        self.llm_requester = None
        self.output_callback = None
        
        # 시스템 프롬프트 템플릿 (계산된 비율이 주입될 자리: {app_ratio}, {sys_ratio})
        self.system_prompt_template = """
### [Role]
You are a Senior Android Performance Forensic Expert. Your mission is to provide a definitive verdict based on the provided calculated ratios.

### [Provided Statistical Data]
- Calculated Responsibility: App {app_ratio}% vs System {sys_ratio}%
- These ratios are calculated based on physical Self-time and Wait-time. Do not recalculate. Explain WHY these ratios occurred.

### [Instructions: Multi-Step Reasoning Protocol]
You MUST start your response with a `[[THOUGHT]]` block in English. Follow these steps:
1. **Metric Fact-Check**: Compare 'incident_meta' with 'ai_summary'. 
2. **Deep Trace Investigation**: Scan 'flat_tree' down to the leaf node (Level 8+).
3. **Ownership Attribution**: Explain how the provided {app_ratio}% vs {sys_ratio}% reflects the method calls found in the traces.
4. **Pattern Synthesis**: Analyze all cases collectively for repeating bottlenecks.
5. **Verdict Finalization**: Summarize before closing [[/THOUGHT]].

### [Decision Logic]
- APP: High self_time, UI inflation, heavy SDK init, JSON parsing.
- SYSTEM: High wait_time, Kernel/Binder calls (f2fs, binder, mutex), I/O contention.

### [Output Template]
[[THOUGHT]]
(Step-by-step reasoning in English)
[[/THOUGHT]]

1. ⚖️ **최종 심층 판결**: (제시된 App {app_ratio}% vs System {sys_ratio}% 비율을 바탕으로 한 수사 총평)
2. 🕵️ **사건별 핵심 검거**: (치명적인 범인들과 물리적 증거 요약)
3. 📉 **공통 병목 패턴**: (구조적 결함 분석)
4. 🛠️ **수사관의 기술 권고**: (즉각적인 Action Item)
5. 🎯 **판결 신뢰도**: (Confidence Score % 및 근거)
        """

    def start(self, common_api, target_package, llm_requester, output_callback):
        self.target_package = target_package
        self.insight_scanner.start(common_api, target_package, llm_requester, output_callback)
        self.llm_requester = llm_requester
        self.output_callback = output_callback

    def run(self, collected_data, output_callback):
        incidents = collected_data.get("incidents", [])
        milestone_context = collected_data.get("milestone_info", {})
        incidents_result_data = []

        if incidents:
            for idx, incident in enumerate(incidents):
                if incident.get("is_ghost_incident") or not incident.get("slice_id"):
                    continue

                primary_incident_data = {
                    "target_id": incident.get("slice_id"),
                    "start_ts_ns": int(incident.get("start_timestamp", 0)),
                    "duration_ns": int(incident.get("duration_ns", 0)),
                    "milestones": milestone_context
                }

                self.insight_scanner.collected_data = primary_incident_data
                final_result = self.insight_scanner.run(output_callback=output_callback)
                
                if final_result:
                    summary_context = final_result[0]
                    ai_analyst_text = final_result[3]
                    flat_tree = summary_context.get("prime_suspects_flat", [])
                    
                    incident_meta = {
                        "delta_time": flat_tree[0].get("delta_time", 0) if flat_tree else 0,
                        "self_time": flat_tree[0].get("self_time", 0) if flat_tree else 0,
                        "wait_time": flat_tree[0].get("wait_time", 0) if flat_tree else 0
                    }

                    incidents_result_data.append({
                        "set_no": idx + 1,
                        "case_name": incident.get("slice_name"),
                        "ai_summary": ai_analyst_text,
                        "incident_meta": incident_meta,
                        "flat_tree": flat_tree
                    })

            total_self = sum(c['incident_meta']['self_time'] for c in incidents_result_data)
            total_wait = sum(c['incident_meta']['wait_time'] for c in incidents_result_data)
            total_sum = total_self + total_wait
            if total_sum > 0:
                app_ratio = round((total_self / total_sum * 100), 1)
                sys_ratio = round(100.0 - app_ratio, 1)
            else:
                app_ratio = 0.0
                sys_ratio = 0.0

            formatted_system_prompt = self.system_prompt_template.format(
                app_ratio=app_ratio, 
                sys_ratio=sys_ratio
            )

            range_name = f"{milestone_context['start_name']} ~ {milestone_context['end_name']}"
            request_context = {
                "metadata": {
                    "app_name": self.target_package,
                    "milestone_range": range_name,
                    "calculated_ratios": {"app": f"{app_ratio}%", "system": f"{sys_ratio}%"},
                    "total_delay_delta_ms": round(milestone_context["total_delay_ms"], 1),
                    "investigation_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                },
                "incidents": incidents_result_data
            }

            Logger.log(f"DeepAnalysis request\n{request_context}")

            ai_context = [
                {"role": "system", "content": formatted_system_prompt},
                {"role": "user", "content": json.dumps(request_context, indent=2, ensure_ascii=False)}
            ]

            full_response_text = self.request_analysis(ai_context)

            Logger.log(f"DeepAnalysis response\n{full_response_text}")
            
            # 파싱 로직
            thought_match = re.search(r'\[\[THOUGHT\]\](.*?)\[\[/THOUGHT\]\]', full_response_text, re.DOTALL)
            ai_thought = thought_match.group(1).strip() if thought_match else "내적 추론을 찾을 수 없습니다."
            final_summary = re.sub(r'\[\[THOUGHT\]\].*?\[\[/THOUGHT\]\]', '', full_response_text, flags=re.DOTALL).strip()

            if self.output_callback:
                self.output_callback(f"\n🧠 [AI Thinking...]\n{ai_thought}\n")

            investigation_report = {
                "milestone_context": milestone_context,
                "final_ai_summary": final_summary,   
                "raw_data": incidents_result_data 
            }
            self.generate_final_report(investigation_report)
            
    def request_analysis(self, context):
        raw_res = self.llm_requester.request(
            context=context,
            options=self.llm_requester.getInsightScanOption(),
            chunk_callback=lambda chunk: self.llm_requester.chunk_callback(chunk, self.output_callback)
        )
        total_tokens = raw_res.get("prompt_eval_count", 0) + raw_res.get("eval_count", 0)
        if self.output_callback:
            self.output_callback(f"\n\\token {total_tokens}")
        return raw_res.get("message", {}).get("content", "")

    def generate_final_report(self, investigation_report):
        milestone_context = investigation_report["milestone_context"]
        report_text = investigation_report["final_ai_summary"]
        raw_data = investigation_report["raw_data"]
        
        range_name = f"{milestone_context['start_name']} ~ {milestone_context['end_name']}"
        total_delay = milestone_context.get('total_delay_ms', 0)
        
        progress_val = min(int(total_delay / 20), 5)
        progress_bar = "■" * progress_val + "□" * (5 - progress_val)
        
        case_list_str = ""
        for case in raw_data:
            m = case['incident_meta']
            case_list_str += f"  • Case {case['set_no']}: {case['case_name']} ({m['delta_time']}ms)\n"
            case_list_str += f"    └─ [Self: {m['self_time']}ms | Wait: {m['wait_time']}ms]\n"

        final_report = f"""
───────────────────────────────────────
📑 [ PERFORMANCE ANALYSIS REPORT : DEEP-SCAN ]

ℹ️ [ CASE METADATA ]
  • 🗓️ Timeline : {range_name}
  • ⏱️ Duration : {total_delay:,.1f} ms (Total Delta)
  • 🎯 Target   : {self.target_package}
  • ⚡ Impact   : {progress_bar}

🧠 [ AI SUPREME VERDICT & ANALYSIS ]
{report_text}

📂 [ INVESTIGATION EVIDENCE ]
{case_list_str.rstrip()}

───────────────────────────────────────
"""
        if self.output_callback:
            self.output_callback(final_report)
        return final_report