import json

from detective_api import DetectiveAPI
from ollama_manager import OllamaManager
from prompt_values import PromptValues


class Executor:
    def __init__(self, model_name="gemma3-12b"):
        self.ollamaManager = OllamaManager(model_name=model_name)

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

        # 1. 검사 장비(API) 초기화
        det_api = DetectiveAPI(trace_normal, trace_slow, target_package)

        # 2. 초기 검사 즉시 실행 (API 1번)
        _out(f"🕵️‍♂️ '{target_package}' 분석을 위한 초기 검사 시작합니다...")
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

        while True:
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
                _out("❌ 에러: AI가 올바른 JSON 형식을 반환하지 않았습니다.")
                break

            status = result.get("status")
            thought = result.get("thought", {})
            _out(f"\n\n🧠 가설: {thought.get('hypothesis', '추론 중...')}")
            _out(f"💡 근거: {thought.get('reasoning', '-')}")

            if status == "investigating":
                tool_calls = result.get("tool_calls", [])
                feedback_data = "### 추가 수사 결과 데이터 ###\n"

                for call in tool_calls:
                    tool_name = call.get("tool")
                    args = call.get("args", {})

                    _out(f"🚀 도구 실행: {tool_name}({args})")

                    if hasattr(det_api, tool_name):
                        tool_func = getattr(det_api, tool_name)
                        data = tool_func(**args)
                        feedback_data += f"\n[{tool_name} 결과]\n{json.dumps(data, indent=2, ensure_ascii=False)}\n"
                    else:
                        feedback_data += f"\n[{tool_name}] 존재하지 않는 도구입니다.\n"

                # 대화 이력 업데이트
                context.append({"role": "assistant", "content": json.dumps(result)})
                context.append({"role": "user", "content": feedback_data})

            elif status == "complete":
                report = result.get("report", {})
                _out("\n" + "=" * 50)
                _out(f"✨ 범인 검거 완료: {report.get('summary')}")
                _out(f"🚩 근본 원인: {report.get('root_cause')}")
                _out("-" * 50)
                _out(f"📊 상세 분석:\n{report.get('analysis_detail')}")
                _out("-" * 50)
                _out(f"✅ 해결책 제안: {report.get('fix_recommendation')}")
                _out("=" * 50)
                break

            else:
                _out("⚠️ 알 수 없는 수사 상태입니다.")
                break

        return lines
