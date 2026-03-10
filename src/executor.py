import json

from detective_api import DetectiveAPI
from ollama_manager import OllamaManager
from prompt_values import PromptValues


class Executor:
    def __init__(self, model_name="gemma3-12b"):
        self.ollamaManager = OllamaManager(model_name=model_name)
        self.max_rounds = 8  # 최대 8라운드까지 수사 진행 (이후 강제 종결)

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
                self._print_final_report(_out, report, final_round=current_round)
                return lines

        # 최대 라운드 초과 시 강제 요약
        _out("\n⚠️ 수사 제한 시간(Max Rounds)이 종료되었습니다. 최종 결론을 도출합니다.")
        context.append(
            {
                "role": "user",
                "content": "수사가 길어지고 있습니다. 지금까지의 $\Delta$ 데이터를 바탕으로 범인을 특정하고 최종 보고서를 작성하십시오.",
            }
        )

        final_res = self.ollamaManager.request(
            context, format="json", chunk_callback=chunk_callback
        )
        try:
            final_result = json.loads(final_res["message"]["content"])
            self._print_final_report(
                _out, final_result.get("report", {}), final_round=current_round
            )
        except:
            _out("❌ 최종 보고서 작성 실패.")

        return lines

    def _print_final_report(self, _out_func, report, final_round=1):
        # 1. AI 응답 데이터 추출 (JSON 규격 준수)
        summary = report.get("summary", "분석 요약 정보 없음")
        root_cause = report.get("root_cause", "원인 특정 불가")
        evidence_summary = report.get("evidence_summary", "")
        analysis_detail = report.get("analysis_detail", "상세 분석 내용 없음")
        checked_tools = report.get("checked_paths", [])  # AI가 사용한 도구 목록
        fix_recommendation = report.get("fix_recommendation", "권장 조치 없음")

        # 2. 동적 신뢰도(Confidence Score) 산출
        score = 0

        # A. 도구 다양성 (최대 40점) - 사용된 고유 도구 개수당 8점
        unique_tools = list(set(checked_tools))
        score += min(len(unique_tools) * 8, 40)

        # B. 증거 상태 판별 (최대 30점)
        # AI의 증거 요약에 확신을 나타내는 키워드가 있는지 검사합니다.
        evidence_lower = evidence_summary.lower()
        if any(
            word in evidence_lower
            for word in ["확보", "입증", "verified", "identified", "범인"]
        ):
            score += 30
        elif any(
            word in evidence_lower for word in ["의심", "probable", "추정", "가능성"]
        ):
            score += 15

        # C. 수사 집요함 (최대 20점) - 5라운드 이상 수사 시 만점
        score += min(final_round * 4, 20)

        # D. 데이터 정밀도 (최대 10점) - 분석 내용의 충실도
        if len(analysis_detail) > 100:
            score += 10
        elif len(analysis_detail) > 50:
            score += 5

        # 3. 점수대별 수사관 소견 매핑
        if score >= 90:
            trust_msg = "⚖️ [범행 확정] 결정적 증거 확보 및 수사 종결"
        elif score >= 75:
            trust_msg = "🔍 [유력 용의자 특정] 높은 신뢰도의 분석 결과"
        elif score >= 60:
            trust_msg = "🧐 [합리적 의심] 정황 근거 유효, 추가 검증 권장"
        elif score >= 40:
            trust_msg = "⚠️ [증거 불충분] 부분적 정황 포착, 수사 범위 확대 필요"
        else:
            trust_msg = "❌ [수사 난항] 데이터 부족으로 인한 낮은 신뢰도"

        # 4. 시각적 요소 구성 (20칸 바)
        filled_blocks = int((score / 100) * 20)
        bar = "█" * filled_blocks + "░" * (20 - filled_blocks)
        db_line = "═" * 70
        sg_line = "─" * 70

        # 5. 리포트 빌드
        res = []
        res.append("\n" + db_line)
        res.append(f"       📜 [ ANDROID PERFORMANCE FORENSIC REPORT ]")
        res.append(db_line)

        res.append(f"📝 분석 요약 (Summary)")
        res.append(f'   "{summary}"')
        res.append("")

        res.append(f"🚩 근본 원인 (Root Cause Identified)")
        res.append(f"   ▶ {root_cause}")
        res.append("")

        res.append(f"🛠️ 수사 경로 및 증거 요약")
        res.append(
            f"   • 사용 도구: {', '.join(checked_tools) if checked_tools else 'N/A'}"
        )
        res.append(f"   • 증거 데이터: {evidence_summary}")

        res.append(sg_line)

        res.append(f"📊 상세 분석 리포트 (Analysis Detail)")
        # 마크다운 표나 긴 텍스트를 깔끔하게 들여쓰기 처리
        for line in analysis_detail.split("\n"):
            if line.strip():
                res.append(f"   {line.strip()}")

        res.append(sg_line)

        res.append(f"✅ 최종 권고 사항 (Fix Recommendation)")
        for line in fix_recommendation.split("\n"):
            if line.strip():
                # 불렛 포인트 자동 생성
                clean_line = line.strip().lstrip("-").lstrip("•").strip()
                res.append(f"   ☞ {clean_line}")

        res.append(db_line)

        # 하단 신뢰도 정보 출력
        footer = f"{trust_msg}  |  신뢰 지수: [{bar}] {score}%"
        res.append(footer.center(70))
        res.append(db_line + "\n")

        # 6. 최종 출력
        _out_func("\n".join(res))
