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
You are the "Chief Android System Performance Forensic Inspector". 
Your mission is to synthesize multiple incident reports into a "Supreme Verdict" using MRI-enriched data.

### [Statistical Constraints]
- **Fixed Ratios**: App {app_ratio}% vs System {sys_ratio}%.
- **Instruction**: These are calculated based on physical metrics (Self vs Wait). Your goal is to justify these ratios using the provided trace evidence.

### [Instructions: Organic CoT Protocol]
Inside the `[[THOUGHT]]` block, you MUST perform:

1. **[MRI Cross-Check]**: 
   - Aggregate `io_wait_ms`, `mutex_wait_ms`, and `runnable_ms` across ALL incidents. 
   - Does the total `io_wait` explain the {sys_ratio}%? (Physical Grounding).

2. **[Timeline Synthesis]**: 
   - Analyze the progression from Case 1 to Case N. 
   - Is there a "Chain Reaction"? (e.g., High I/O in Case 1 causing scheduling delay in Case 2).

3. **[Pattern Detection]**: 
   - Identify "Common Enemies": Recurring method names or system calls across different incidents.
   - Look for "Spamming": Many small slices (Minor_Slices_Sum) indicating fragmented logic.

4. **[Responsibility Mapping]**: 
   - Connect {app_ratio}% to App-side logic (Inflation, SDK init, heavy loops).
   - Connect {sys_ratio}% to Kernel/Hardware states (Storage I/O, Lock contention, CPU migration).

5. **[Final Technical Theory]**: Summarize the root cause of the entire milestone delay.

### [Output Template: Supreme Verdict]
[[THOUGHT]]
(Detailed forensic reasoning in English)
[[/THOUGHT]]

1. ⚖️ **최종 심층 판결 (Supreme Verdict)**
   - (제시된 {app_ratio}% vs {sys_ratio}% 비율의 정당성을 MRI 지표를 근거로 선언)

2. 🕵️ **사건별 핵심 물증 (Evidence Summary)**
   - (각 Case별로 어떤 물리적 지표(I/O, Mutex 등)가 결정적이었는지 핵심 노드 ID와 함께 요약)

3. 📉 **구조적 병목 패턴 (Systemic Defect)**
   - (여러 사건에서 공통적으로 발견된 구조적 문제점 - 예: "초기 로딩 시 UFS 대역폭 포화", "특정 싱글톤 객체의 Lock 경합")

4. 🛠️ **수사관의 기술 권고 (Actionable Advice)**
   - **[App Team]**: (로직 수정, Lazy Loading, 락 범위 축소 등)
   - **[System/Kernel Team]**: (I/O 우선순위 조정, 스케줄링 정책 점검 등)

5. 🎯 **판결 신뢰도 및 근거**
   - (Confidence Score % 및 데이터 정합성(Ghost Gap 0 여부 등)에 근거한 확신 수준)
        """

    def start(self, common_api, target_package, llm_requester, output_callback):
        self.target_package = target_package
        self.insight_scanner.start(common_api, target_package, llm_requester, output_callback)
        self.llm_requester = llm_requester
        self.output_callback = output_callback

    def run(self, collected_data, output_callback):
        incidents = collected_data.get("incidents", [])
        milestone_context = collected_data.get("milestone_info", {})
        captured_delay_ms = collected_data.get("captured_delay_ms", 0)
        overlap_factor = collected_data.get("overlap_factor", 0)
        coverage_efficiency = collected_data.get("coverage_efficiency", 0)
        concurrency_mode = collected_data.get("concurrency_mode", 0)
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

                    if not flat_tree: continue
                    root = flat_tree[0] # 루트 노드
                    
                    # 단순 수치만 가져오지 않고, V4.2의 핵심 'physical_stats'를 통째로 가져옵니다.
                    incident_meta = {
                        "delta_ms": root.get("delta_time", 0),
                        "self_ms": root.get("self_time", 0),
                        "wait_ms": root.get("wait_time", 0),
                        "mri_stats": root.get("physical_stats", {})
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
                    "investigation_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "captured_delay_ms": captured_delay_ms,
                    "coverage_efficiency": coverage_efficiency,
                    "overlap_factor": overlap_factor,
                    "concurrency_mode": concurrency_mode
                },
                "incidents": incidents_result_data
            }

            Logger.log(f"DeepAnalysis request\n{request_context}")

            ai_context = [
                {"role": "system", "content": formatted_system_prompt},
                {"role": "user", "content": json.dumps(request_context, indent=2, ensure_ascii=False)}
            ]

            full_response_text = self.request_analysis(ai_context)

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