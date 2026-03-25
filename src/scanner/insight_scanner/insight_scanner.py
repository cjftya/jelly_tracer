from scanner.base_scanner import BaseScanner
from scanner.insight_scanner.insight_scan_data_delegate import InsightScanDataDelegate
from scanner.insight_scanner.insight_scan_ai_delegate import InsightScanAIDelegate

class InsightScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        self.collected_data = None  # 1차 분석 결과(마스터 데이터)
        self.data_provider = None
        self.ai_analyst = None

    def start(self, common_api, target_package, ollama_manager, output_callback):
        super().start(common_api, target_package, ollama_manager, output_callback)
        if self.data_provider is None:
            self.data_provider = InsightScanDataDelegate(output_callback)
            self.data_provider.init(common_api, target_package)
        else:
            self.data_provider.output_callback = output_callback
            
        if self.ai_analyst is None:
            self.ai_analyst = InsightScanAIDelegate(ollama_manager, output_callback)
        else:
            self.ai_analyst.output_callback = output_callback
    
    def run(self, output_callback=None):  
        if output_callback:
            self.output_callback = output_callback
            self.data_provider.output_callback = output_callback
            self.ai_analyst.output_callback = output_callback
        
        self.output_callback(f"🚀 [Insight-Scan] Investigation Started: {self.target_package}")

        # 1. 마스터 데이터 존재 확인
        if not self.collected_data:
            self.output_callback("⚠️ [Error] Master data (collected_data) is missing. Cannot proceed.", True)
            return

        try:
            # 2. 2차 심층 데이터 추출 (SQL Drilling)
            # 수정된 Delegate는 collected_data를 직접 받아 데이터를 추출합니다.
            self.output_callback("🔬 Drilling into trace layers ...")
            deep_dive_evidences = self.data_provider.fetch_deep_dive_package(self.collected_data)
            deep_dive_evidence = deep_dive_evidences[0]
            for_report = deep_dive_evidences[1]

            if not deep_dive_evidence:
                self.output_callback("⚠️ [Error] Deep dive evidence is missing. Cannot proceed.", True)
                return

            # 3. 최종 AI 분석용 마스터 브리핑 패키지 조립 (JSON 통합)
            # 1차의 컨텍스트와 2차의 물리적 증거를 결합합니다.
            master_brief = {
                "analysis_context": self.collected_data, 
                "deep_dive_evidence": deep_dive_evidence,
                "for_report": for_report
            }

            # 4. 2단계 AI 추론 엔진 가동 (Phase 1: 탐사 -> Phase 2: 검증)
            self.output_callback("🧠 AI Analyst is synthesizing deep insights...")
            verdicts = self.ai_analyst.execute_double_scan(master_brief)
            final_verdict = verdicts[0]
            target_node = verdicts[1]

            # # 5. 최종 결과 출력 및 수사 종료
            self.build_final_report(
                ai_summary_report=final_verdict,
                target_node=target_node,
                tree_data=for_report
            )

        except Exception as e:
            self.output_callback(f"❌ [Critical Error] Insight Scan failed: {str(e)}", True)

    def stop(self):
        pass

    def format_tree_visual(self, node, prefix="", is_last=True, is_root=True, target_id=None):
        # 1. 트리 마커 설정
        marker = "└── " if is_last else "├── "
        if is_root: marker = "📍 "
        
        # 2. 데이터 추출 및 타겟 하이라이트
        node_id = node.get('slice_id', '-')
        is_target = (str(node_id) == str(target_id))
        
        # 타겟일 경우 '▶' 표시와 볼드체 느낌의 강조
        current_marker = f"▶ {marker}" if is_target else f"  {marker}"
        
        name = node.get('name', 'Unknown')
        # 이름이 너무 길면 잘림 방지 및 정렬을 위해 30자로 제한
        display_name = (name[:27] + '..') if len(name) > 30 else name
        
        delta = node.get('delta_time', 0)
        wait = node.get('wait_time', 0)
        self_time = node.get('self_time', 0) # 수사관님을 위한 Self Time 추가
        
        # 3. 위험 플래그 시각화
        flags = []
        if node.get('is_native_cliff'): flags.append("🪨[N]")
        if node.get('is_resource_contention'): flags.append("⚠️[R]")
        if node.get('has_ghost_gap'): flags.append("👻[G]")
        flag_str = " ".join(flags)

        # 4. 한 줄 구성 (컬럼 간격 최적화)
        # 이름(30) | ID(8) | Delta(8) | Wait(8) | Self(8) | Flags
        line = (f"{prefix}{current_marker}{display_name:<30} "
                f"(ID: {node_id:<7}) | "
                f"{delta:>7.1f}ms | "
                f"W: {wait:>6.1f}ms | "
                f"S: {self_time:>6.1f}ms "
                f"{flag_str}\n")

        # 5. 자식 노드 재귀 호출
        children = node.get('children', [])
        result = line
        new_prefix = prefix + ("    " if is_last or is_root else "│   ")
        
        for i, child in enumerate(children):
            last_child = (i == len(children) - 1)
            result += self.format_tree_visual(child, new_prefix, last_child, False, target_id)
            
        return result

    def build_final_report(self, ai_summary_report, target_node, tree_data):
        # 1. 기본 데이터 추출
        milestones = self.collected_data['milestones']
        start_milestone_name = milestones['start_name']
        end_milestone_name = milestones['end_name']
        milestone_delay = milestones["total_delay_ms"]

        target_data = self.collected_data['target_data']
        target_id = target_data['target_id']
        target_duration = target_data['duration_ms']
        target_name = target_node.get('name', 'N/A') if target_node else "N/A"

        # 2. 전수 조사 데이터 생성
        table = self.format_tree_visual(node=tree_data)

        # 3. 시각적 지표 계산 (프로그레스 바)
        impact_percent = (target_duration / milestone_delay) * 100
        bar_width = 20
        filled = int((impact_percent / 100) * bar_width)
        progress_bar = f"[{'█' * filled}{'░' * (bar_width - filled)}] {impact_percent:.1f}%"

        # 4. 심각도 아이콘 및 코멘트 선정
        if impact_percent >= 80:
            icon, status = "🔴", "CRITICAL: 대부분의 지연을 차지하는 독보적 원인"
        elif impact_percent >= 50:
            icon, status = "🟠", "WARNING: 상당 부분을 차지하는 주요 개선 필요 지점"
        else:
            icon, status = "🟡", "NOTICE: 주요 병목 중 하나이며 하위 노드 검토 필요"

        # 5. AI 리포트 들여쓰기 정렬 (가독성 향상)
        indented_ai_report = ai_summary_report.replace('\n', '\n  ')

        # 6. 디자인이 적용된 최종 양식 구성
        final_report_text = f"""
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🚀 SYSTEM PERFORMANCE FORENSIC REPORT                     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
  📍 Range  : {start_milestone_name}  ➔  {end_milestone_name}
  ⏱️ Total  : {milestone_delay:,.1f} ms
  🎯 Target : {target_name} (ID: {target_id})
  📊 Impact : {progress_bar}
  {icon} Status : {status}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🔍 [AI ROOT CAUSE ANALYSIS]
  {indented_ai_report}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📂 [FULL TRACE STACK]
{table}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        # 결과 출력
        self.output_callback("\n" + final_report_text)