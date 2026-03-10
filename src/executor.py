import json
import datetime
from detective_api import DetectiveAPI
from ollama_manager import OllamaManager
from prompt_values import PromptValues


class Executor:
    def __init__(self, model_name="gemma3-12b"):
        self.ollamaManager = OllamaManager(model_name=model_name)
        self.max_rounds = 8  # 최대 8라운드까지 수사 진행 (이후 강제 종결)
        self.investigation_history = []

    def run(self, trace_normal, trace_slow, target_package, output_callback=None):
        def _out(msg: str="", system: bool=False):
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

        # 1. 검사 장비(API) 및 초기 스캔
        det_api = DetectiveAPI(trace_normal, trace_slow, target_package)
        _out(f"🔍 [시스템 가동] 수사를 시작합니다.\n")

        # Phase 1 즉시 실행
        first_scan = det_api.initial_system_scan(target_package)
        self.investigation_history.append({
            "step": "INITIAL_SCAN",
            "tool": "initial_system_scan",
            "evidence": first_scan
        })

        # 2. 대화 컨텍스트 구성
        context = [
            {
                "role": "system",
                "content": PromptValues.getSystemPrompt(target_package=target_package),
            },
            {
                "role": "user",
                "content": f"Phase 1 초기 스캔 결과입니다:\n{first_scan}\n\n위 데이터를 분석하고 SOP에 따라 다음 수사 단계를 결정하십시오.",
            },
        ]

        while current_round <= self.max_rounds:
            # 컨텍스트 관리: 오래된 라운드의 대형 테이블 데이터를 요약본으로 교체 (토큰 절약)
            if current_round >= 3:
                target_round_label = f"### {current_round - 2}라운드 수사 결과 ###"
                for i in range(len(context)):
                    if (
                        context[i]["role"] == "user"
                        and target_round_label in context[i]["content"]
                    ):
                        context[i][
                            "content"
                        ] = f"{target_round_label} [데이터 요약됨: 이전 추론에 반영]"

            _out(f"\n🎬 [ROUND {current_round}] 수사관이 증거를 검토 중입니다...")

            # AI에게 질문 (Strict JSON 모드)
            response = self.ollamaManager.request(
                context, format="json", chunk_callback=chunk_callback
            )

            # 토큰 사용량 체크 (Ollama 기준)
            total_used_token = response.get("prompt_eval_count", 0) + response.get(
                "eval_count", 0
            )
            _out("\\token " + str(total_used_token))

            try:
                result = json.loads(response["message"]["content"])
            except json.JSONDecodeError:
                _out("❌ 에러: AI가 올바른 JSON 형식을 반환하지 않았습니다.\n")
                break

            status = result.get("status", "investigating")
            thought = result.get("thought", {})

            # 사고 과정 출력
            _out(f"🧠 단계: {thought.get('phase', '알 수 없음')}")
            _out(f"🧐 가설: {thought.get('hypothesis', '-')}")
            _out(f"🎯 관찰: {thought.get('observation_review', '-')}")

            if status == "investigating":
                tool_calls = result.get("tool_calls", [])
                if not tool_calls:
                    _out("⚠️ 경고: 수사관이 도구를 사용하지 않았습니다. 재요청합니다.")
                    context.append(
                        {
                            "role": "user",
                            "content": "SOP에 따라 분석 도구를 최소 하나 호출하십시오.",
                        }
                    )
                    continue

                # SOP 준수: 여러 도구를 호출해도 첫 번째 도구만 우선 처리 (혹은 루프 처리)
                # 여기서는 지휘관님의 '한 라운드에 하나' 원칙에 따라 첫 번째 도구에 집중합니다.
                call = tool_calls[0]
                tool_name = call.get("tool")
                args = call.get("args", {})

                _out(f"🛠️ [API CALL] {tool_name}({args})", system=True)

                feedback_data = f"### {current_round}라운드 수사 결과 ###\n"

                if hasattr(det_api, tool_name):
                    tool_func = getattr(det_api, tool_name)
                    try:
                        # API 실행 (마크다운 문자열 반환)
                        data_md = tool_func(**args)
                        feedback_data += f"\n{data_md}"
                        self.investigation_history.append({
                            "step": f"STEP {current_round}",
                            "tool": tool_name,
                            "evidence": data_md
                        })

                        _out(f"✅ {tool_name}: 데이터 확보 완료 ({len(data_md)} bytes)", system=True)
                    except Exception as e:
                        feedback_data += f"\n❌ 실행 에러: {str(e)}"
                        _out(f"❌ {tool_name} 실행 오류: {str(e)}", system=True)
                else:
                    feedback_data += (
                        f"\n❌ 에러: {tool_name}은(는) 존재하지 않는 장비입니다."
                    )
                    _out(f"⚠️ 존재하지 않는 도구 호출 시도: {tool_name}", system=True)

                # 컨텍스트 업데이트
                context.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                context.append(
                    {
                        "role": "user",
                        "content": f"{feedback_data}\n\n위 데이터를 50% 법칙 및 SOP에 따라 분석하고 다음 단계를 결정하십시오.",
                    }
                )
                current_round += 1

            elif status == "complete":
                report = result.get("report", {})
                final_report = self._request_final_report_refinement(context, report)
                self._print_final_report(_out, final_report, final_round=current_round)
                return lines

        # 최대 라운드 초과 시 강제 요약
        _out("\n⚠️ 수사 제한 시간(Max Rounds)이 종료되었습니다. 최종 결론을 도출합니다.")
        all_evidence_str = "\n".join([
            f"### {h['step']} ({h['tool']}) 결과 ###\n{h['result']}" 
            for h in self.investigation_history
        ])

        force_summary_prompt = f"""
            [긴급] 수사 시간이 초과되었습니다. 
            지금까지 확보된 아래의 모든 증거 데이터를 종합하여 범인을 특정하고 최종 보고서를 작성하십시오.

            확보된 증거 리스트:
            {all_evidence_str}

            지침:
            1. 확실하지 않은 경우 '추정 원인'으로 기재하되, 데이터 수치는 정확히 인용하라.
            2. 각 STEP별 Delta 수치를 표와 함께 포함하여 analysis_detail을 작성하라.
            """

        context.append({
            "role": "user",
            "content": force_summary_prompt
        })

        final_res = self.ollamaManager.request(
            context, format="json", chunk_callback=chunk_callback
        )
        try:
            final_result = json.loads(final_res["message"]["content"])
            report = final_result.get("report", {})

            if not report.get("checked_paths"):
                report["checked_paths"] = [h["tool"] for h in self.investigation_history]

            self._print_final_report(_out, report, final_round=current_round)
        except:
            _out("❌ 최종 보고서 작성 실패.")

        return lines

    def _request_final_report_refinement(self, context, initial_report):
        """저장된 모든 변수(증거)를 사용하여 리포트의 analysis_detail을 풍성하게 만듭니다."""
        all_evidence = "\n\n".join([f"[{h['step']}] {h['evidence']}" for h in self.investigation_history])
        
        refine_prompt = f"""
        지금까지 수집된 모든 증거 데이터(Tables)이다:
        {all_evidence}

        이 데이터들을 바탕으로 최종 리포트의 'analysis_detail' 섹션을 작성하라. 
        각 STEP별로 사용한 도구와 구체적인 Delta($\Delta$) 수치를 표와 함께 포함하여 매우 상세하게 작성하라.
        """
        # AI에게 최종 정제 요청 (간략화된 예시 로직)
        initial_report["analysis_detail"] = self.ollamaManager.request_text(refine_prompt)
        initial_report["checked_paths"] = [h["tool"] for h in self.investigation_history]
        return initial_report

    def _print_final_report(self, _out_func, report, final_round=1):
        # 1. 데이터 추출 (AI가 생성한 JSON에서 데이터 확보)
        summary = report.get("summary", "분석 요약 정보 없음")
        root_cause = report.get("root_cause", "원인 특정 불가")
        evidence_summary = report.get("evidence_summary", "확보된 직접 증거 없음")
        analysis_detail = report.get("analysis_detail", "상세 분석 내용 없음")
        checked_tools = report.get("checked_paths", [])
        fix_recommendation = report.get("fix_recommendation", "권장 조치 없음")
        
        # 2. 메타데이터 생성 (전문 문서 감성 추가)
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        case_id = f"TD-CASE-{now.strftime('%y%m%d%H%M')}"
        
        # 3. 시각적 가이드라인 정의
        db_line = "═" * 76
        sg_line = "─" * 76
        
        res = []
        
        # [A] Header Section: 공식 문서 박스 아트
        res.append(f"\n╔{db_line}╗")
        res.append(f"║{'PERFORMANCE FORENSIC INVESTIGATION REPORT'.center(76)}║")
        res.append(f"╚{db_line}╝")
        res.append(f"  [ CASE ID ]  {case_id:25} [ TIMESTAMP ]  {timestamp}")
        res.append(db_line)

        # [B] Executive Summary: 무엇이 문제인가?
        res.append(f" 📝 [ 분석 요약 ]")
        res.append(f"    \"{summary}\"")
        res.append("")

        # [C] Root Cause Identified: 범인은 누구인가?
        res.append(f" 🚩 [ 근본 원인 특정 ]")
        res.append(f"    ▶ {root_cause}")
        res.append("")

        # [D] Investigation Path: 어떤 도구를 썼는가?
        res.append(f" 🛠️ [ 수사 경로 및 도구 ]")
        tools_str = ", ".join(checked_tools) if checked_tools else "기본 시스템 스캔"
        res.append(f"    • 운용 도구: {tools_str}")
        res.append(f"    • 핵심 증거: {evidence_summary}")
        res.append(sg_line)

        # [E] Deep Dive Analysis: 지휘관님이 만든 8개 API의 결과물 (By Tool)
        res.append(f" 📊 [ 상세 부검 리포트 (By Tool) ]")
        
        # AI가 작성한 상세 내용을 한 줄씩 읽으며 포맷팅
        lines = analysis_detail.split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            
            # 1) 도구별 섹션 헤더 강조 (STEP, TOOL, API 등의 키워드 감지)
            if any(keyword in stripped.upper() for keyword in ["STEP", "TOOL", "API", "탐지", "###"]):
                # 기존 마크다운 샵(#) 기호 제거 후 깔끔하게 출력
                clean_header = stripped.lstrip('#').strip()
                res.append(f"\n    ● {clean_header}")
                
            # 2) 마크다운 표(Table) 보존: 파이프(|) 기호가 있으면 들여쓰기 최소화
            elif "|" in stripped:
                res.append(f"      {stripped}")
                
            # 3) 일반 분석 코멘트
            else:
                # 불렛 포인트가 이미 있다면 그대로 쓰고, 없다면 하이픈 추가
                prefix = "" if stripped.startswith(("-", "*", "•")) else "- "
                res.append(f"      {prefix}{stripped}")
                
        res.append("\n" + sg_line)

        # [F] Final Verdict: 어떻게 해결할 것인가?
        res.append(f" ✅ [ 최종 권고 사항 ]")
        for line in fix_recommendation.split("\n"):
            if line.strip():
                # 불렛 포인트를 '☞' 아이콘으로 통일
                clean_line = line.strip().lstrip("-").lstrip("•").lstrip("☞").strip()
                res.append(f"    ☞ {clean_line}")

        res.append(db_line)
        
        # [G] Footer: 수사 종결 선언
        footer = f"END OF INVESTIGATION - TRACEDETECTIVE v1.3"
        res.append(footer.center(76))
        res.append(db_line + "\n")

        _out_func("\n".join(res))
