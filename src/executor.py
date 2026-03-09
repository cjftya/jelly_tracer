import json

from detective_api import DetectiveAPI
from ollama_manager import OllamaManager
from prompt_values import PromptValues


class Executor:
    def __init__(self, model_name="gemma3-12b"):
        self.ollamaManager = OllamaManager(model_name=model_name)
        self.max_rounds = 8  # 최대 8라운드까지 수사 진행 (이후 강제 종결)

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
        first_scan_compressed = json.dumps(
            first_scan, ensure_ascii=False, separators=(",", ":")
        )

        # 3. 대화 컨텍스트 구성
        context = [
            {
                "role": "system",
                "content": PromptValues.getSystemPrompt(target_package=target_package),
            },
            {
                "role": "user",
                "content": f"초기 검사 결과 보고서입니다:\n{first_scan_compressed}",
            },
        ]
        # print(first_scan_compressed)
        # print(det_api.profile_main_thread())
        # print(det_api.analyze_memory_gc())
        # print(det_api.check_lock_contention())
        # print(det_api.check_thread_states())
        # print(det_api.profile_thread_functions())
        # print(det_api.trace_binder_calls())

        while current_round <= self.max_rounds:
            if current_round >= 3:
                clean_target_round = current_round - 2
                target_label = f"### {clean_target_round}라운드 수사 결과 ###"

                for i in range(len(context)):
                    if (
                        context[i]["role"] == "user"
                        and target_label in context[i]["content"]
                    ):
                        # 상세 데이터는 날리고 '표지석'만 남깁니다.
                        context[i][
                            "content"
                        ] = f"{target_label} [데이터 요약: 이전 추론에 반영됨]"

            _out(f"🎬 [ROUND {current_round}] 데이터를 분석 중입니다...\n\n")

            # AI에게 질문 (Strict JSON 모드)
            response = self.ollamaManager.request(
                context, format="json", chunk_callback=chunk_callback
            )
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
            _out(f"🧠 가설: {thought.get('hypothesis', '원인 미상')}\n")
            _out(f"💡 근거: {thought.get('reasoning', '-')}\n")

            if status == "investigating":
                tool_calls = result.get("tool_calls", [])
                if not tool_calls:
                    _out(
                        "⚠️ 경고: 수사관이 도구를 선택하지 않았습니다. 추가 분석을 요청합니다."
                    )
                    context.append(
                        {
                            "role": "user",
                            "content": "분석을 위해 최소 하나 이상의 도구를 호출하십시오.",
                        }
                    )
                    continue

                feedback_data = f"### {current_round}라운드 수사 결과 ###\n"

                for call in tool_calls:
                    tool_name = call.get("tool")
                    args = call.get("args", {})

                    _out(f"🛠️ API 호출: {tool_name}({args})")

                    if hasattr(det_api, tool_name):
                        tool_func = getattr(det_api, tool_name)
                        try:
                            data = tool_func(**args)
                            compressed_data = json.dumps(
                                data, ensure_ascii=False, separators=(",", ":")
                            )
                            feedback_data += f"\n[{tool_name}]:{compressed_data}"
                        except Exception as e:
                            feedback_data += (
                                f"\n[{tool_name} 에러] 실행 중 문제 발생: {str(e)}"
                            )

                    else:
                        feedback_data += f"\n[{tool_name}]:존재하지 않는 도구"

                # 대화 이력 업데이트 (Assistant/User 메시지 모두 압축 저장)
                context.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            result, ensure_ascii=False, separators=(",", ":")
                        ),
                    }
                )
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
                "content": "수사 시간이 종료되었습니다. 지금까지 확보된 $\Delta$ 데이터를 기반으로 결론을 요약하십시오.",
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
        # 1. 데이터 추출 및 기본값 설정
        summary = report.get("summary", "N/A")
        root_cause = report.get("root_cause", "N/A")
        evidence = report.get("evidence_data", {})
        status = evidence.get("status", "Unknown")
        tools = evidence.get("checked_tools", [])
        current_round = report.get("final_round", 1)
        analysis_detail = report.get("analysis_detail", "내용 없음")
        fix_recommendation = report.get("fix_recommendation", "내용 없음")

        # 2. 동적 신뢰도(Confidence Score) 산출 로직
        score = 0
        # A. 도구 다양성 (최대 40점) - 도구 하나당 10점
        score += min(len(tools) * 10, 40)
        # B. 증거 상태 (최대 30점)
        if status.lower() == "verified":
            score += 30
        elif status.lower() == "probable":
            score += 15
        # C. 수사 집요함 (최대 20점) - 라운드당 4점 (5라운드 이상 시 만점)
        score += min(current_round * 4, 20)
        # D. 데이터 정밀도 (최대 10점) - 상세 내용 존재 시
        if len(analysis_detail) > 50:
            score += 10

        # 3. 점수대별 수사관의 소견 (Multi-tier Message)
        if score >= 95:
            trust_msg = "⚖️ [범행 확정] 결정적 증거 확보 및 분석 종결"
        elif score >= 85:
            trust_msg = "🔍 [유력 용의자 특정] 고도로 신뢰할 수 있는 분석 결과"
        elif score >= 70:
            trust_msg = "🧐 [합리적 의심] 정황 근거 유효하나 추가 검증 권장"
        elif score >= 50:
            trust_msg = "⚠️ [증거 불충분] 부분적 정황 포착, 수사 범위 확대 필요"
        else:
            trust_msg = "❌ [수사 난항] 데이터 부족으로 인한 분석 신뢰도 낮음"

        # 4. 텍스트 기반 신뢰도 바 생성 (20칸)
        filled_blocks = int((score / 100) * 20)
        bar = "█" * filled_blocks + "░" * (20 - filled_blocks)

        # 5. 리포트 빌드
        db_line = "═" * 65
        sg_line = "─" * 65

        res = []
        res.append("\n" + db_line)
        res.append(f"📜 [ TRACEDETECTIVE ANALYSIS REPORT : v1.2 ]")
        res.append(db_line)

        res.append(f"📝 분석 요약")
        res.append(f'   "{summary}"')
        res.append("")

        res.append(f"🚩 근본 원인 (Root Cause)")
        res.append(f"   ▶ {root_cause}")
        res.append("")

        res.append(f"🔍 증거 상태 및 사용 도구")
        res.append(f"   [{status}] 🛠️ {', '.join(tools) if tools else 'None'}")

        res.append(sg_line)

        res.append(f"📊 상세 분석 데이터 (Analysis Detail)")
        for line in analysis_detail.split("\n"):
            if line.strip():
                res.append(f"   • {line.strip()}")

        res.append(sg_line)

        res.append(f"✅ 최종 권고 사항 (Fix Recommendation)")
        for line in fix_recommendation.split("\n"):
            if line.strip():
                res.append(f"   ☞ {line.strip()}")

        res.append(db_line)
        # 하단 신뢰도 정보 정렬
        footer = f"{trust_msg} | 신뢰도: [{bar}] {score}%"
        res.append(footer.rjust(65))
        res.append(db_line + "\n")

        # 6. 최종 출력 함수 호출
        _out_func("\n".join(res))
