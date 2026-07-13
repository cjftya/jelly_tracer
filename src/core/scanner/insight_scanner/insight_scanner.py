from core.scanner.base_scanner import BaseScanner
from core.scanner.insight_scanner.insight_scan_data_delegate import InsightScanDataDelegate
from core.scanner.insight_scanner.insight_scan_ai_delegate import InsightScanAIDelegate
from typing import List, Optional, Any, Dict

class InsightScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        self.collected_data: Optional[Dict[str, Any]] = None  # 1차 분석 결과(마스터 데이터)
        self.data_provider: Optional[InsightScanDataDelegate] = None
        self.ai_analyst: Optional[InsightScanAIDelegate] = None

    def start(self, common_api, target_package, llm_requester, output_callback):
        super().start(common_api, target_package, llm_requester, output_callback)
        if self.data_provider is None:
            self.data_provider = InsightScanDataDelegate(output_callback)
            self.data_provider.init(common_api, target_package)
        else:
            self.data_provider.output_callback = output_callback
            
        if self.ai_analyst is None:
            self.ai_analyst = InsightScanAIDelegate(llm_requester, output_callback)
        else:
            self.ai_analyst.output_callback = output_callback
    
    def run(self, output_callback=None) -> Optional[list]:
        if output_callback:
            self.output_callback = output_callback
            if self.data_provider:
                self.data_provider.output_callback = output_callback
            if self.ai_analyst:
                self.ai_analyst.output_callback = output_callback
        
        if not self.output_callback:
            return None
            
        self.output_callback(f"🚀 [Insight-Scan] Investigation Started: {self.target_package}")

        if not self.data_provider or not self.ai_analyst:
            self.output_callback("⚠️ [Error] Data provider or AI analyst is missing. Cannot proceed.", True)
            return None

        if not self.collected_data:
            self.output_callback("⚠️ [Error] Master data (collected_data) is missing. Cannot proceed.", True)
            return None

        self.data_provider.set_normal_baseline(self.collected_data.get("normal_baseline", None))

        try:
            self.output_callback("🔬 Drilling into trace layers ...")
            deep_dive_evidences = self.data_provider.fetch_deep_dive_package(self.collected_data)
            deep_dive_evidence = deep_dive_evidences[0]
            full_tree_evidence = deep_dive_evidences[1]

            if not deep_dive_evidence:
                self.output_callback("⚠️ [Error] Deep dive evidence is missing. Cannot proceed.", True)
                return None

            summary_context = self.data_provider.summarize_investigation(self.target_package, self.collected_data['milestones'],
                                                        self.collected_data['overall_timeline_context'], deep_dive_evidence, full_tree_evidence)

            raw_res = self.ai_analyst.request_analysis(summary_context, fact_only=self.collected_data.get("fact_only", False))

            if not raw_res or "error" in raw_res:
                error_msg = raw_res.get("error", "Unknown AI error") if raw_res else "No response from AI"
                self.output_callback(f"⚠️ AI Analysis failed: {error_msg}", True)
                return None

            final_report = self.generate_final_report(summary_context, raw_res)
            thinking_text = raw_res.get('thinking', 'No thinking content available.')
            ai_analyst_text = raw_res.get('analysis', 'No analysis content available.')
            indented_ai_report = "\n".join([f"  {line}" for line in ai_analyst_text.split('\n')])
            return [summary_context, final_report, thinking_text, indented_ai_report]
        except Exception as e:
            self.output_callback(f"❌ [Critical Error] Insight Scan failed: {str(e)}", True)

    def stop(self):
        super().stop()

    def format_tree_visual(self, node, prefix="", is_last=True, is_root=True, target_id=None):
        # 1. 트리 마커 설정
        marker = "└── " if is_last else "├── "
        if is_root: marker = "📍 "
        
        # 2. 데이터 추출 및 타겟 하이라이트
        node_id = node.get('slice_id', '-')
        is_target = (str(node_id) == str(target_id))
        
        # 타겟일 경우 '▶' 표시와 볼드체 느낌의 강조
        current_marker = f"▶ {marker}" if is_target else f"  {marker}"
        
        display_name = node.get('name', 'Unknown')
        
        delta = node.get('delta_time', 0)
        wait = node.get('wait_time', 0)
        self_time = node.get('self_time', 0)
        ghost_gap = node.get('ghost_gap', 0)
        
        # 4. 한 줄 구성 (컬럼 간격 최적화)
        line = (f"{prefix}{current_marker}{display_name:<30} "
                f"(ID: {node_id:<7}) | "
                f"D: {delta:>7.1f}ms | "
                f"W: {wait:>6.1f}ms | "
                f"S: {self_time:>6.1f}ms | "
                f"G: {ghost_gap:>6.1f}ms\n")

        # 5. 자식 노드 재귀 호출
        children = node.get('children', [])
        result = line
        new_prefix = prefix + ("    " if is_last or is_root else "│   ")
        
        for i, child in enumerate(children):
            last_child = (i == len(children) - 1)
            result += self.format_tree_visual(child, new_prefix, last_child, False, target_id)
            
        return result

    def generate_final_report(self, summary_context, ai_res):
        # 1. 메타데이터 및 지연 시간 추출
        meta = summary_context.get('metadata', {})
        verdict = summary_context.get('final_verdict', {})
        ratios = verdict.get('responsibility_ratio', {'app': 0, 'system': 0})
        
        # 지연된 시간
        milestone_delay = meta.get('total_delay_delta_ms', 0) 
        
        # 타임라인 분리
        range_str = meta.get('milestone_range', 'Unknown ~ Unknown')
        start_name, end_name = range_str.split(' ~ ') if ' ~ ' in range_str else (range_str, "")

        # 노말라이즈된 값 (0~100%)
        app_ratio = ratios.get('app', 0)
        sys_ratio = ratios.get('system', 0)
        app_blocks = round(app_ratio / 10)
        sys_blocks = round(sys_ratio / 10)

        # 2. 프로그레스 바 생성
        progress_bar = (
            f"[App({app_ratio}%) {'█' * app_blocks}{'░' * (10 - app_blocks)}┃"
            f"{'█' * sys_blocks}{'░' * (10 - sys_blocks)} Sys({sys_ratio}%)]"
        )

        # 3. 지연 시간에 따른 상태 및 아이콘 자동 결정
        if milestone_delay >= 50:
            icon, status = "🚨", "CRITICAL SYSTEMIC BOTTLENECK"
        elif milestone_delay >= 20:
            icon, status = "⚠️", "WARNING: PERFORMANCE DEGRADATION"
        else:
            icon, status = "✅", "NORMAL PERFORMANCE RANGE"

        # 4. AI 보고서 들여쓰기 처리
        analysis_text = ai_res.get('analysis', 'No analysis content available.')
        indented_ai_report = "\n".join([f"  {line}" for line in analysis_text.split('\n')])

        # 5. 트리 비주얼 생성
        target_id = ai_res.get('target_id', 0)
        tree_table = self.format_tree_visual(summary_context.get('evidence_room_full_tree', {}), target_id=target_id)

        # 6. 최종 템플릿 조립
        report = f"""
───────────────────────────────────────
📑 [ PERFORMANCE ANALYSIS REPORT ]

ℹ️ [ CASE METADATA ]
  • 🗓️ Timeline : {start_name} ➔ {end_name}
  • ⏱️ Duration : {milestone_delay:,.1f} ms (Delta)
  • 🎯 Target   : {meta.get('app_name')} (ID: {target_id})
  • 🚥 Status   : {icon} {status}

🧠 [ AI ROOT CAUSE ANALYSIS ]
{indented_ai_report}

📂 [ CRITICAL TRACE STACK ]
{tree_table}
───────────────────────────────────────
"""
        return report