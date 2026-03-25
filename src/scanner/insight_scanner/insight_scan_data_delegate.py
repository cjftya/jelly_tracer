import re
import pandas as pd

class InsightScanDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.output_callback = output_callback
        self.package = None

    def init(self, common_api, target_package):
        self._common_api = common_api
        self.package = target_package

    def fetch_deep_dive_package(self, collected_data):
        return self._generate_intensive_scan_single(collected_data)

    def _generate_intensive_scan_single(self, collected_data, max_depth=6, culling_threshold=0.0):
        target = collected_data.get("target_data", {})
        try:
            t_id = int(target.get("target_id", 0))
            start_ns = int(target.get("start_ts_ns", 0))
            dur_ns = int(target.get("duration_ns", 0))
            end_ns = start_ns + dur_ns
        except (ValueError, TypeError):
            self.output_callback("🚨 [Error] Invalid numeric data in collected_data.", True)
            return None

        # 1. 루트 노드 정보 및 해당 스레드 ID(utid) 역추적
        # slice ID를 알면 thread_track을 통해 utid를 바로 찾을 수 있습니다.
        query = f"""
            SELECT s.name, tt.utid 
            FROM slice s 
            JOIN thread_track tt ON s.track_id = tt.id 
            WHERE s.id = {t_id}
        """
        res = self._common_api.tp_s.query(query).as_pandas_dataframe()
        if res.empty:
            self.output_callback(f"🚨 [Error] Slice ID {t_id} not found in trace.", True)
            return None
            
        root_name = res.iloc[0]['name']
        utid_s = int(res.iloc[0]['utid'])

        # 2. 기준점 설정: 이 루트 노드의 전체 실행 시간을 100% 임팩트로 설정
        s_metrics = self._get_node_metrics_by_id(self._common_api.tp_s, utid_s, t_id, start_ns, end_ns)
        total_case_duration = s_metrics['dur']

        self.output_callback(f"🎯 [Target Locked] {root_name} (ID: {t_id}) | Duration: {total_case_duration:.1f}ms", True)

        # 3. 재귀적 수직 탐색 시작 (Normal 비교 없이 Absolute 모드로 진행)
        return self._build_recursive_node_pro(
            slice_id=t_id,
            name=root_name,
            utid=utid_s,
            depth=1,
            max_depth=max_depth,
            total_case_dur=total_case_duration,
            bounds_s=[start_ns, end_ns],
            threshold=culling_threshold
        )

    def _build_recursive_node_pro(self, slice_id, name, utid, depth, max_depth, total_case_dur, bounds_s, threshold):
        if depth > max_depth:
            return None

        # 1. 현재 노드 지표 추출 및 로컬 변수화
        s_metrics = self._get_node_metrics_by_id(self._common_api.tp_s, utid, slice_id, bounds_s[0], bounds_s[1])
        
        delta = round(s_metrics['dur'], 1)
        self_val = round(s_metrics['self'], 1)
        wait_val = round(s_metrics['wait'], 1)
        impact_ratio = round(delta / total_case_dur, 3) if total_case_dur > 0 else 0

        # 2. Native 패턴 미리 체크
        native_patterns = r"Native|JNI|0x|postAndWait|acquire|wait|lock|monitor|Sync"
        is_pattern_match = bool(re.search(native_patterns, name, re.IGNORECASE))

        # 3. 기본 노드 데이터 구조 초기화
        node_data = {
            "name": name,
            "target_id": int(slice_id),
            "delta_time": delta, 
            "self_time": self_val,
            "wait_time": wait_val,
            "impact_ratio": impact_ratio,
            "children": []
        }

        children_total_delta = 0.0

        # 4. 자식 노드 탐색 및 재귀 호출
        if depth < max_depth:
            children_df = self._get_structural_children(self._common_api.tp_s, slice_id)
            
            for _, child in children_df.iterrows():
                child_dur = child['dur'] / 1e6
                child_impact = child_dur / total_case_dur if total_case_dur > 0 else 0

                if child_impact < threshold:
                    continue

                child_node = self._build_recursive_node_pro(
                    child['id'], child['name'], utid, depth + 1, 
                    max_depth, total_case_dur, bounds_s, threshold
                )
                
                if child_node:
                    node_data["children"].append(child_node)
                    children_total_delta += child_node["delta_time"]

        # 5. Ghost Gap 계산
        g_gap = round(max(0, delta - children_total_delta - self_val - wait_val), 1)
        node_data["ghost_gap"] = g_gap

        # 6. ✅ 최종 Precomputed Flags 확정 (모든 계산이 끝난 후)
        # - Native Cliff: 자식이 없고(Leaf) AND self_time >= 5ms AND 패턴 일치
        node_data["is_native_cliff"] = (not node_data["children"]) and (self_val >= 5.0) and is_pattern_match
        
        # - Resource Contention: Wait Time이 전체의 80% 초과 (수사 원칙)
        node_data["is_resource_contention"] = (wait_val / delta > 0.8) if delta > 0 else False
        
        # - Ghost Gap 유무
        node_data["has_ghost_gap"] = g_gap > 5.0

        # 7. 컬링 조건 확인 (본인 영향력 미미 + 자식 없음)
        if impact_ratio < threshold and not node_data["children"] and depth > 1:
            return None

        return node_data

    def _get_node_metrics_by_id(self, tp, utid, slice_id, start_ts=None, end_ts=None):
        # 1. 슬라이스 기본 정보 및 직계 자식들의 실행 시간 합계 추출
        query = f"""
            SELECT ts, dur, 
            (SELECT SUM(dur) FROM slice WHERE parent_id = {slice_id}) as child_dur 
            FROM slice WHERE id = {slice_id}
        """
        res = tp.query(query).as_pandas_dataframe()
        if res.empty: 
            return {'dur': 0, 'self': 0, 'wait': 0, 'raw_ts': 0, 'raw_dur': 0}
        
        row = res.iloc[0]
        s_ts = row['ts']
        s_dur = row['dur']
        c_dur_ns = row['child_dur'] or 0 
        
        # 2. 실제 분석 범위(Clipping) 결정: 슬라이스가 분석 구간을 벗어나지 않도록 보정
        analysis_start = max(s_ts, start_ts) if start_ts is not None else s_ts
        analysis_end = min(s_ts + s_dur, end_ts) if end_ts is not None else s_ts + s_dur
        analysis_dur_ns = analysis_end - analysis_start

        if analysis_dur_ns <= 0:
            return {'dur': 0, 'self': 0, 'wait': 0, 'raw_ts': 0, 'raw_dur': 0}

        # 3. Thread State 정밀 쿼리
        # 해당 슬라이스 기간 내의 각 상태별 점유 시간을 계산합니다.
        state_query = f"""
            SELECT 
                state, 
                SUM(CASE 
                    WHEN ts < {analysis_start} THEN ts + dur - {analysis_start}
                    WHEN ts + dur > {analysis_end} THEN {analysis_end} - ts
                    ELSE dur 
                END) as clipped_dur_ns
            FROM thread_state 
            WHERE utid = {utid} 
            AND ts + dur > {analysis_start} 
            AND ts < {analysis_end} 
            GROUP BY 1
        """
        st_res = tp.query(state_query).as_pandas_dataframe()
        
        # 4. 메트릭 산출 로직 (정밀 수사 모드)
        
        # [Running] 실제로 CPU에서 연산을 수행한 시간
        running_time_ms = st_res[st_res['state'].isin(['Running', 'Run'])]['clipped_dur_ns'].sum() / 1e6
        
        # [Runnable] CPU를 할당받으려고 줄 서서 기다린 시간 ('R')
        runnable_time_ms = st_res[st_res['state'] == 'R']['clipped_dur_ns'].sum() / 1e6
        
        # [Blocked] I/O, Disk, 혹은 Lock으로 인해 멈춘 시간 ('D', 'DK', 'S' 등 상황에 따라 추가)
        blocked_time_ms = st_res[st_res['state'].isin(['D', 'DK', 'S'])]['clipped_dur_ns'].sum() / 1e6
        
        full_dur_ms = analysis_dur_ns / 1e6

        # Self Time: (전체 시간 - 자식들이 쓴 시간) -> 순수하게 이 함수 레벨에서 소모한 시간
        self_time_ms = max(0, full_dur_ms - (c_dur_ns / 1e6))
        
        # Wait Time: (Runnable + Blocked) -> 로직 실행 외에 외부 요인으로 지연된 시간
        wait_time_ms = runnable_time_ms + blocked_time_ms

        return {
            'dur': round(full_dur_ms, 2),
            'self': round(self_time_ms, 2),
            'wait': round(wait_time_ms, 2),
            'raw_ts': s_ts,
            'raw_dur': s_dur
        }

    def _get_structural_children(self, tp, parent_id):
        """부모 ID를 기준으로 하위 슬라이스들을 실행 시간이 긴 순서대로 추출합니다."""
        query = f"""
            SELECT id, name, ts, dur 
            FROM slice 
            WHERE parent_id = {parent_id} 
            ORDER BY dur DESC 
            LIMIT 10
        """
        return tp.query(query).as_pandas_dataframe()