import json

from detective_api import DetectiveAPI
from ollama_manager import OllamaManager
from prompt_values import PromptValues


class Executor:
    def __init__(self, model_name="gemma3-12b"):
        self.ollamaManager = OllamaManager(model_name=model_name)
        self.max_rounds = 5

    def run(self, trace_normal, trace_slow, target_package, output_callback=None):
        def _out(msg: str):
            if output_callback:
                output_callback(msg)
            else:
                print(msg)
            lines.append(msg)

        lines: list[str] = []
        spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        chunk_count = [0]

        def chunk_callback(chunk):
            spinner_msg = f"\r💬 추론 중... {spinner[chunk_count[0] % len(spinner)]}"
            if output_callback:
                output_callback(spinner_msg)
            else:
                print(spinner_msg, end="", flush=True)
            chunk_count[0] += 1

        current_round = 1

        # 1. 검사 장비(API) 초기화
        det_api = DetectiveAPI(trace_normal, trace_slow, target_package)

        # 2. 초기 검사 즉시 실행 (API 1번)
        _out(f"🕵️‍♂️ '{target_package}' 분석을 위한 초기 검사 시작합니다...\n\n")
        first_scan = det_api.initial_system_scan(target_package)

        # 3. 대화 컨텍스트 구성
        context = [
            {
                "role": "system",
                "content": PromptValues.getSystemPrompt(target_package=target_package),
            },
            {
                "role": "user",
                "content": f"초기 검사 결과 보고서입니다:\n{json.dumps(first_scan, indent=2, ensure_ascii=False)}",
            },
        ]

        while current_round <= self.max_rounds:
            _out(f"🎬 [ROUND {current_round}] 데이터를 분석 중입니다...\n\n")

            # AI에게 질문 (Strict JSON 모드)
            response = self.ollamaManager.request(
                context, format="json", chunk_callback=chunk_callback
            )
            total_used_token = response.get("prompt_eval_count", 0) + response.get(
                "eval_count", 0
            )
            _out("\token " + str(total_used_token))

            try:
                result = json.loads(response["message"]["content"])
            except json.JSONDecodeError:
                _out("❌ 에러: AI가 올바른 JSON 형식을 반환하지 않았습니다.\n")
                break

            status = result.get("status")
            thought = result.get("thought", {})
            _out(f"🧠 가설: {thought.get('hypothesis', '추론 중...')}\n")
            _out(f"💡 근거: {thought.get('reasoning', '-')}\n")

            if status == "investigating":
                tool_calls = result.get("tool_calls", [])
                feedback_data = f"### {current_round}라운드 수사 결과 ###\n"

                for call in tool_calls:
                    tool_name = call.get("tool")
                    args = call.get("args", {})

                    _out(f"🛠️ API 호출: {tool_name}({args})")

                    if hasattr(det_api, tool_name):
                        tool_func = getattr(det_api, tool_name)
                        data = tool_func(**args)
                        feedback_data += f"\n[{tool_name} 결과]\n{json.dumps(data, indent=2, ensure_ascii=False)}\n"
                    else:
                        feedback_data += f"\n[{tool_name}] 존재하지 않는 도구입니다.\n"

                # 대화 이력 업데이트
                context.append({"role": "assistant", "content": json.dumps(result)})
                context.append({"role": "user", "content": feedback_data})
                current_round += 1  # 다음 라운드로 진행

            elif status == "complete":
                report = result.get("report", {})
                self._print_final_report(_out, report)
                return lines

        # 강제 종결 (최대 라운드 도달)
        _out("\n⚠️ 지정된 수사 라운드를 모두 소모했습니다. 강제 요약을 요청합니다.")
        context.append(
            {
                "role": "user",
                "content": "시간이 다 되었습니다. 지금까지 수집된 증거만으로 최선의 미결 보고서를 작성하십시오.",
            }
        )
        final_res = self.ollamaManager.request(
            context, format="json", chunk_callback=chunk_callback
        )

        try:
            final_result = json.loads(final_res["message"]["content"])
            final_report = final_result.get("report", {})
            self._print_final_report(_out, final_report)
        except json.JSONDecodeError:
            _out("❌ 에러: AI가 올바른 JSON 형식을 반환하지 않았습니다.\n")

        return lines

    def _print_final_report(self, _out_func, report):
        # 1. evidence_data 추출 (기본값 설정)
        evidence = report.get("evidence_data", {})
        status = evidence.get("status", "Unknown")
        checked_paths = evidence.get("checked_paths", [])

        # 실행된 API 목록을 보기 좋게 문자열로 변환
        paths_str = ", ".join(checked_paths) if checked_paths else "기록 없음"

        _out_func("\n" + "═" * 60)
        _out_func(f"📜 [수사 결과 요약] {report.get('summary')}")
        _out_func(f"🚩 [근본 원인] {report.get('root_cause')}")

        # 🔍 신규 추가: 수사의 투명성을 증명하는 라인
        _out_func(f"🔍 [증거 확보 상태] {status} (수색 경로: {paths_str})")

        _out_func("─" * 60)
        _out_func(f"📊 [상세 분석]\n{report.get('analysis_detail')}")
        _out_func(f"✅ [조치 권고]\n{report.get('fix_recommendation')}")
        _out_func("═" * 60 + "\n")
