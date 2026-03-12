import datetime
import json

from detective_api import DetectiveAPI
from ollama_manager import OllamaManager
from prompt_values import PromptValues
from trace_server_manager import TraceServerManager


class Executor:
    def __init__(self):
        self.ollamaManager = None
        self.server_manager = None
        self.max_rounds = 8
        self.investigation_history = []

    def start(self):
        if self.ollamaManager is None:
            self.ollamaManager = OllamaManager()
            self.ollamaManager.start_engine()
        if self.server_manager is None:
            self.server_manager = TraceServerManager()

    def stop(self):
        if self.ollamaManager:
            self.ollamaManager.stop_engine()
        if self.server_manager:
            self.server_manager.stop_servers()

    def run(self, trace_normal, trace_slow, target_package, model_name=None, output_callback=None):
        if model_name:
            self.ollamaManager.set_model_name(model_name)
        self.server_manager.stop_servers()
        self.server_manager.start_servers(trace_normal, trace_slow)

        def _out(msg: str = "", system: bool = False):
            if output_callback:
                output_callback(msg, system)
            else:
                print(f"[{'SYSTEM' if system else 'AI'}] {msg}")
            lines.append(msg)

        lines: list[str] = []
        spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        chunk_count = [0]

        def chunk_callback(chunk):
            spinner_msg = f"\r💬 추론 중... {spinner[chunk_count[0] % len(spinner)]}"
            if output_callback:
                output_callback(spinner_msg, False)
            else:
                print(spinner_msg, end="", flush=True)
            chunk_count[0] += 1

        current_round = 1
        last_coverage = 0.0
        stagnation_count = 0

        # 1. 검사 장비(API) 및 초기 스캔
        det_api = DetectiveAPI(trace_normal, trace_slow, target_package)
        _out(f"🔍 [시스템 가동] 수사를 시작합니다.\n")

        # Phase 1 즉시 실행
        first_scan = det_api.initial_system_scan(target_package)
        self.investigation_history.append(
            {
                "step": "INITIAL_SCAN",
                "tool": "initial_system_scan",
                "args": {"keyword": target_package},
                "evidence": first_scan
            }
        )

        # 2. 대화 컨텍스트 구성 시 라벨 추가
        context = [
            {
                "role": "system",
                "content": PromptValues.getSystemPrompt(target_package=target_package),
            },
            {
                "role": "user",
                "content": f"### Round 0: Initial System Scan ###\n{first_scan}\n\nAnalyze and call the next tool per SOP.",
            },
        ]

        print(det_api.get_device_info())

        # while current_round <= self.max_rounds:
        #     _out(f"\n🎬 [ROUND {current_round}] 수사관이 증거를 검토 중입니다...")

        #     # AI에게 질문 (Strict JSON 모드)
        #     response = self.ollamaManager.request(
        #         context, format="json", chunk_callback=chunk_callback
        #     )

        #     # 토큰 사용량 체크 (Ollama 기준)
        #     total_used_token = response.get("prompt_eval_count", 0) + response.get(
        #         "eval_count", 0
        #     )
        #     _out("\\token " + str(total_used_token))

        #     try:
        #         result = json.loads(response["message"]["content"])
        #     except json.JSONDecodeError:
        #         _out("❌ 에러: AI가 올바른 JSON 형식을 반환하지 않았습니다.\n")
        #         break

        #     status = result.get("status", "investigating")
        #     thought = result.get("thought", {})

        #     # 사고 과정 출력
        #     _out(f"🧠 단계: {thought.get('phase', '알 수 없음')}")
        #     _out(f"🧐 가설: {thought.get('hypothesis', '-')}")
        #     _out(f"🎯 관찰: {thought.get('observation_review', '-')}")

        #     if status == "investigating":
        #         tool_calls = result.get("tool_calls", [])
        #         if not tool_calls:
        #             _out("⚠️ 경고: 수사관이 도구를 사용하지 않았습니다. 재요청합니다.")
        #             context.append(
        #                 {
        #                     "role": "user",
        #                     "content": "Please invoke at least one analysis tool according to the SOP.",
        #                 }
        #             )
        #             continue

        #         # SOP 준수: 여러 도구를 호출해도 첫 번째 도구만 우선 처리 (혹은 루프 처리)
        #         call = tool_calls[0]
        #         tool_name = call.get("tool")
        #         args = call.get("args", {})

        #         is_duplicate = any(
        #             h["tool"] == tool_name and h.get("args") == args 
        #             for h in self.investigation_history
        #         )

        #         _out(f"🛠️ [API CALL] {tool_name}({args})", system=True)

        #         feedback_data = f"### Round {current_round} Investigation Results ###\n"
        #         if is_duplicate:
        #             _out(f"🚫 [중복 차단] {tool_name}({args}) 중복 호출", system=True)
        #             data_md = f"[SYSTEM] Redundant call: {tool_name}({args}). Path already explored. PIVOT per **Coverage Rule**."
        #             feedback_data += f"\n{data_md}"

        #         elif hasattr(det_api, tool_name):
        #             tool_func = getattr(det_api, tool_name)
        #             try:
        #                 data_md = tool_func(**args)
        #                 feedback_data += f"\n{data_md}"

        #                 # 지분율 변화가 거의 없는지 체크 (0.1% 미만 차이)
        #                 current_coverage = self._extract_coverage(data_md)
        #                 if abs(current_coverage - last_coverage) < 0.1:
        #                     stagnation_count += 1
        #                 else:
        #                     stagnation_count = 0
        #                 last_coverage = current_coverage

        #                 # 2회 연속 정체 시 AI에게 강력한 피벗 압박 추가
        #                 if stagnation_count >= 2:
        #                     _out("⚠️ 분석 정체 감지: 가설 전환 유도", system=True)
        #                     feedback_data += f"\n[SYSTEM] Warning: Coverage stalled at {current_coverage}%. DEAD-END detected. Change your hypothesis NOW."

        #                 self.investigation_history.append(
        #                     {
        #                         "step": f"STEP {current_round}",
        #                         "tool": tool_name,
        #                         "args": args,
        #                         "evidence": data_md
        #                     }
        #                 )
        #                 _out(
        #                     f"✅ {tool_name}: 데이터 확보 완료 ({len(data_md)} bytes)",
        #                     system=True,
        #                 )
        #             except Exception as e:
        #                 feedback_data += f"\n❌ Execution Error: {str(e)}"
        #                 _out(f"❌ {tool_name} 실행 오류: {str(e)}", system=True)
        #         else:
        #             feedback_data += (
        #                 f"\n❌ Error: {tool_name} is an unknown or invalid tool."
        #             )
        #             _out(f"⚠️ 존재하지 않는 도구 호출 시도: {tool_name}", system=True)

        #         # 컨텍스트 업데이트
        #         context.append(
        #             {
        #                 "role": "assistant",
        #                 "content": json.dumps(result, ensure_ascii=False),
        #             }
        #         )
        #         context.append(
        #             {
        #                 "role": "user",
        #                 "content": f"{feedback_data}\n\nAnalyze based on the **Coverage Rule**/SOP and decide the next step.",
        #             }
        #         )
        #         current_round += 1

        #     elif status == "complete" or (current_round == self.max_rounds):
        #         report = result.get("report", {})

        #         if status == "complete":
        #             final_status = report.get("status", "complete")
        #         else:
        #             final_status = report.get("status", "unresolved")
        #         report["status"] = final_status
        #         final_report = self._request_final_report_refinement(context, report)
        #         self._print_final_report(_out, final_report, final_round=current_round)
        #         return lines

        return lines

    def _extract_coverage(self, text: str) -> float:
        if not text:
            return 0.0

        match = re.search(r"Latency\s+Coverage:\s*(\d+(?:\.\d+)?)[\s]*%", text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, IndexError):
                return 0.0
        return 0.0

    def _request_final_report_refinement(self, context, initial_report):
        all_evidence = "\n\n".join(
            [
                f"[{h['step']}] {h['tool']} results:\n{h['evidence']}"
                for h in self.investigation_history
            ]
        )

        refine_prompt = f"""
            [TASK: FINAL INVESTIGATION REPORT REFINEMENT]
            Below is the accumulated evidence from all investigation rounds:
            {all_evidence}

            Based on this data, rewrite the 'analysis_detail' section of the final report.

            [STRICT REQUIREMENTS]:
            1. LANGUAGE: KOREAN (한국어).
            2. STRUCTURE: For each STEP, describe: Tool Name, Objective, and Key Findings.
            3. DATA: Include Markdown tables for each step. Ensure $\Delta$ (Delta) values are accurate.
            4. MATH: You MUST use LaTeX for all Delta values (e.g., $\Delta$ 45.2ms).
            5. COVERAGE: Explicitly mention the 'Latency Coverage' contributed by each key finding.
            
            Do not include any introductory remarks. Start with the step-by-step forensic detail.
        """

        # AI에게 최종 정제 요청 (결과물은 한글로 생성됨)
        response = self.ollamaManager.request(
            refine_prompt, chunk_callback=chunk_callback
        )

        refined_detail = None
        if isinstance(response, dict) and "message" in response:
            refined_detail = response["message"]["content"]
        else:
            refined_detail = str(response)

        initial_report["analysis_detail"] = refined_detail
        initial_report["checked_paths"] = [
            h["tool"] for h in self.investigation_history
        ]

        return initial_report

    def _print_final_report(self, _out_func, report, final_round=1):
        # 1. 데이터 추출 및 상태 정의
        status = report.get("status", "unresolved").lower()
        accounting = report.get("latency_coverage", "N/A (0%)")
        summary = report.get("summary", "분석 요약 정보 없음")
        root_cause = report.get("root_cause", "근본 원인 특정 불가")
        evidence_summary = report.get("evidence_summary", "확보된 직접 증거 없음")
        analysis_detail = report.get("analysis_detail", "상세 분석 내용 없음")
        checked_tools = report.get("checked_paths", [])
        fix_recommendation = report.get("fix_recommendation", "권장 조치 없음")

        # 2. 상태별 메타데이터 매핑 (감정을 배제한 객관적 레이블)
        status_configs = {
            "complete": {
                "header": "✅ [ ANALYSIS CERTIFIED ]",
                "label": "VERIFIED (수학적 증명 완료)",
                "icon": "🟢"
            },
            "partial": {
                "header": "⚠️ [ ANALYSIS PARTIAL ]",
                "label": "INCOMPLETE (데이터 지분 부족)",
                "icon": "🟡"
            },
            "unresolved": {
                "header": "❌ [ ANALYSIS UNRESOLVED ]",
                "label": "INSUFFICIENT (증거 불충분)",
                "icon": "🔴"
            }
        }
        cfg = status_configs.get(status, status_configs["unresolved"])

        # 3. 메타데이터 생성
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        case_id = f"TD-CASE-{now.strftime('%y%m%d%H%M')}"
        db_line = "═" * 78
        sg_line = "─" * 78

        res = []

        # [A] Header Section: 공식 문서 박스 아트
        res.append(f"\n╔{db_line}╗")
        res.append(f"║{'PERFORMANCE FORENSIC INVESTIGATION REPORT'.center(78)}║")
        res.append(f"╚{db_line}╝")
        res.append(f"  [ CASE ID ]  {case_id:26} [ TIMESTAMP ]  {timestamp}")
        res.append(db_line)

        # [B] Executive Summary & Data Accounting
        res.append(f" 📝 [ EXECUTIVE SUMMARY ]")
        res.append(f'    "{summary}"')
        res.append("")
        res.append(f" 🚩 {cfg['header']}")
        res.append(f"    ▶ Data Accounting : {cfg['icon']} {cfg['label']}")
        res.append(f"    ▶ Latency Coverage    : {accounting}")
        res.append("")

        # [C] Root Cause Identified: 범인 지목
        res.append(f" 🎯 [ ROOT CAUSE IDENTIFIED ]")
        res.append(f"    ▶ {root_cause}")
        res.append("")

        # 🔥 [ADD] Device Environment: 하드웨어 컨디션 분석 섹션
        device_info = report.get("device_info")
        if device_info is not None:
            res.append(f" 📱 [ DEVICE ENVIRONMENT CONTEXT ]")
            
            # DataFrame 형태로 들어온 경우 표로 변환
            if hasattr(device_info, 'iterrows'):
                res.append(f"    | Metric     | Normal (Baseline)    | Slow (Target)        | Status    |")
                res.append(f"    |{'-'*12}|{'-'*22}|{'-'*22}|{'-'*11}|")
                
                n = device_info[device_info['type'] == 'Normal'].iloc[0]
                s = device_info[device_info['type'] == 'Slow'].iloc[0]
                
                mhz_status = "✅ Stable" if n['avg_cpu_mhz'] == s['avg_cpu_mhz'] else "⚠️ Delta"
                load_val = float(s['total_sys_load_pct'].replace('%', ''))
                load_status = "🔥 Heavy" if load_val > 90 else "✅ Normal"
                core_status = "✅ Same" if n['primary_core_type'] == s['primary_core_type'] else "⚠️ Change"

                res.append(f"    | Avg CPU    | {n['avg_cpu_mhz']:<19} | {s['avg_cpu_mhz']:<19} | {mhz_status:<8} |")
                res.append(f"    | Load       | {n['total_sys_load_pct']:<19} | {s['total_sys_load_pct']:<19} | {load_status:<8} |")
                res.append(f"    | Core       | {n['primary_core_type']:<19} | {s['primary_core_type']:<19} | {core_status:<8} |")

            res.append("\n    [ 용어 해설 ]")
            res.append("    • Avg CPU: 평균 동작 속도 (단위: MHz) - 낮을수록 기기 발열로 인한 성능 제한 상태")
            res.append("    • Load: 시스템 과부하 (단위: %) - 높을수록 다른 앱의 간섭으로 인해 실행이 지연됨")
            res.append("    • Core: 핵심 코어 배정 (Big/Little) - 고성능(Big) 혹은 저전력(Little) 코어 사용 여부")
            
        # [D] Investigation Path: 분석 궤적
        res.append(f" 🛠️ [ INVESTIGATION PATH ]")
        tools_str = ", ".join(checked_tools) if checked_tools else "기본 시스템 스캔"
        res.append(f"    • Tools Used    : {tools_str}")
        res.append(f"    • Key Evidence  : {evidence_summary}")
        res.append(sg_line)

        # [E] Deep Dive Analysis: 상세 부검 내용
        res.append(f" 📊 [ FORENSIC ANALYSIS DETAIL ]")
        
        for line in analysis_detail.split("\n"):
            stripped = line.strip()
            if not stripped: continue

            # 섹션 헤더 강조
            if any(k in stripped.upper() for k in ["STEP", "TOOL", "API", "탐지", "###"]):
                clean_header = stripped.lstrip("#").strip()
                res.append(f"\n    ● {clean_header}")
            # 표(Table) 보존
            elif "|" in stripped:
                res.append(f"      {stripped}")
            # 지분율(Coverage)이 언급된 라인 강조
            elif "Coverage" in stripped or "지분" in stripped:
                res.append(f"      📌 {stripped}")
            # 일반 분석 코멘트
            else:
                prefix = "" if stripped.startswith(("-", "*", "•", "1.", "2.", "3.")) else "- "
                res.append(f"      {prefix}{stripped}")

        res.append("\n" + sg_line)

        # [F] Final Verdict: 해결책 및 제언
        res.append(f" ✅ [ RECOMMENDATIONS ]")
        for line in fix_recommendation.split("\n"):
            if line.strip():
                clean_line = line.strip().lstrip("-").lstrip("•").lstrip("☞").strip()
                res.append(f"    ☞ {clean_line}")

        res.append(db_line)

        # [G] Footer: 수사 종결
        footer = f"END OF INVESTIGATION - TRACEDETECTIVE v1.32"
        res.append(footer.center(78))
        res.append(db_line + "\n")

        _out_func("\n".join(res))
