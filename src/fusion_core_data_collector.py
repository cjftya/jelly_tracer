import re
import json
import os
from datetime import datetime

class FusionCoreDataCollector:
    def __init__(self):
        pass

    def collect_point_scan_data(self, scanner, ai_history, final_report_md):
        final_ai_msg = ai_history[-1]["content"] if ai_history else ""

        def extract_tag(tag):
            # 태그 정밀 도려내기 (마크다운 및 대괄호 대응)
            pattern = rf"(?:\*\*?|\[?)\s*{tag}\s*(?:\]?|\*\*?)\s*[:：]\s*(.*?)(?=\n\s*\[|\n\s*\*\*\[|\n\s*[A-Z]\[|$)"
            match = re.search(pattern, final_ai_msg, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip() if match else "N/A"

        # 1. 시공간 좌표 확정
        final_scope_n, final_scope_s = scanner.scope_stack[-1] if scanner.scope_stack else (None, None)

        # 2. 물적 증거 식별자 추출 (8라운드 전체 전수 조사)
        all_conv_text = " ".join([m["content"] for m in ai_history])
        correlation_ids = list(set(re.findall(r"(0x[0-9a-fA-F]+|Binder:\d+|TID:\d+)", all_conv_text)))

        # 3. 오답 노트 (최근 3개 스코프)
        ignore_history = [str(scope) for scope in scanner.investigated_scopes[-3:]]

        # 🧠 [지능형 브리핑 생성] REASONING 섹션 추출 및 최적화
        reasoning_full = extract_tag("REASONING")
        if reasoning_full == "N/A":
            reasoning_full = final_ai_msg

        cleaned_reasoning = re.sub(r'\s+', ' ', reasoning_full)
        brief_limit = 600 

        if len(cleaned_reasoning) > brief_limit:
            # 문장 단위로 끊어주는 지능형 절삭
            last_period = cleaned_reasoning.rfind('.', 0, brief_limit)
            if last_period > brief_limit * 0.7:
                final_brief = cleaned_reasoning[:last_period + 1]
            else:
                final_brief = cleaned_reasoning[:brief_limit] + "..."
        else:
            final_brief = cleaned_reasoning

        # 4. 마스터 JSON 조립
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
        file_name = f"point_scan_({scanner.target_package})_({timestamp})"
        master_data = {
            "scan_type": "point",
            "metadata": {
                "investigation_id": file_name,
                "target_package": scanner.target_package,
                "target_thread": scanner.target_thread,
                "exported_at": datetime.now().isoformat(),
                "num_cpus": getattr(scanner.data_provider, 'num_cpus', 8)
            },
            "target_window": {
                "start_ms": final_scope_s[0] if final_scope_s else 0,
                "end_ms": final_scope_s[1] if final_scope_s else 0,
                "margin_ms": 50.0
            },
            "targeting": {
                "correlation_ids": correlation_ids[:10],
                "backtrack_count": scanner.backtrack_count,
                "confidence_score": 0.95 if "🔴" in extract_tag("V") else 0.75
            },
            "compression_guide": {
                "investigated_depth": len(scanner.scope_stack),
                "ignore_history": ignore_history,
                "reference_delta": {
                    "app_pct": extract_tag("A"),
                    "sys_pct": extract_tag("S")
                }
            },
            "forensic_intel": {
                "verdict": extract_tag("V"),
                "owner": extract_tag("O"),
                "cause_korean": extract_tag("C"),
                "reasoning_brief": final_brief 
            },
            "raw_archives": {
                "full_ai_history": ai_history,
                "final_report_md": final_report_md
            }
        }

        # 5. 파일 시스템에 영구 박제
        dir_name = f"point_scan_({scanner.target_package})"
        save_dir = f"./investigations/{dir_name}/"
        os.makedirs(save_dir, exist_ok=True)
        
        json_file = os.path.join(save_dir, f"{file_name}.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(master_data, f, indent=2, ensure_ascii=False)
            
        return json_file