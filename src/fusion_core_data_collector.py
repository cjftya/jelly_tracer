import re
import json
import os
from datetime import datetime

class FusionCoreDataCollector:
    def __init__(self):
        pass

    def collect_point_scan_data(self, scanner, ai_history, final_report_md):
        # 1. 마지막 응답 확보 (태그 추출용)
        # ai_history는 <think>가 제거된 정제된 기록입니다.
        final_ai_msg = ai_history[-1]["content"] if ai_history else ""

        def extract_tag(tag):
            # 대괄호([])나 마크다운(**)이 섞인 태그를 정밀하게 추출
            pattern = rf"(?:\*\*?|\[?)\s*{tag}\s*(?:\]?|\*\*?)\s*[:：]\s*(.*?)(?=\n\s*\[|\n\s*\*\*\[|\n\s*[A-Z]\[|$)"
            match = re.search(pattern, final_ai_msg, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip() if match else "N/A"

        # 2. 지능형 브리핑 생성 (생각 아카이브 활용)
        reasoning_full = "N/A"
        if hasattr(scanner.ai_analyst, 'thought_archive') and scanner.ai_analyst.thought_archive:
            last_thought_raw = scanner.ai_analyst.thought_archive[-1]["full_content"]
            thought_match = re.search(r'<think>(.*?)</think>', last_thought_raw, re.DOTALL)
            reasoning_full = thought_match.group(1).strip() if thought_match else last_thought_raw

        cleaned_reasoning = re.sub(r'\s+', ' ', reasoning_full)
        brief_limit = 600 
        final_brief = (cleaned_reasoning[:brief_limit] + "...") if len(cleaned_reasoning) > brief_limit else cleaned_reasoning

        # 3. 마스터 JSON 조립 (누락 데이터 전면 보강)
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
        file_name = f"point_scan_({scanner.target_package})_({timestamp})"
        
        # 조사된 스코프들을 문자열 리스트로 변환 (insight 중복 분석 방지용)
        ignore_history = [f"N:{s[0]}, S:{s[1]}" for s in scanner.investigated_scopes]

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
                "start_ns": scanner.scope_stack[-1][1][0] if scanner.scope_stack else 0,
                "end_ns": scanner.scope_stack[-1][1][1] if scanner.scope_stack else 0,
                "margin_ms": 50.0
            },
            "targeting": {
                "backtrack_count": getattr(scanner, 'backtrack_count', 0),
                "confidence_score": 0.95 if "🔴" in extract_tag("V") else 0.75,
                "pivot_candidates": getattr(scanner.data_provider, 'pivot_candidates', [])
            },
            "compression_guide": {
                "investigated_depth": len(scanner.scope_stack),
                "ignore_history": ignore_history,
                "reference_delta": {
                    "app_pct": extract_tag("A"), # 📱 누락 데이터 추가
                    "sys_pct": extract_tag("S")  # ⚙️ 누락 데이터 추가
                }
            },
            "forensic_intel": {
                "verdict": extract_tag("V"),
                "owner": extract_tag("O"),
                "cause_korean": extract_tag("C"),
                "action_items": extract_tag("T"), # 🛠️ 누락 데이터 추가
                "reasoning_brief": final_brief 
            },
            "raw_archives": {
                "clean_ai_history": ai_history,
                "thought_archive": getattr(scanner.ai_analyst, 'thought_archive', []),
                "final_report_md": final_report_md
            }
        }

        # 4. 저장 로직
        save_dir = f"./investigations/point_scan_({scanner.target_package})/"
        os.makedirs(save_dir, exist_ok=True)
        
        json_file = os.path.join(save_dir, f"{file_name}.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(master_data, f, indent=2, ensure_ascii=False)
            
        return json_file