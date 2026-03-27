import re
import datetime
import pandas as pd

class InsightScanDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.output_callback = output_callback
        self.package = None
        # 자식들이 부모 지연의 70% 이상을 점유해야 '의미 있는 상속'으로 간주
        self.INHERITANCE_THRESHOLD = 0.7 

    def init(self, common_api, target_package):
        self._common_api = common_api
        self.package = target_package

    def fetch_deep_dive_package(self, collected_data):
        for_report = self._generate_intensive_scan_single(collected_data, is_flat=False)
        return [self._generate_intensive_scan_single(collected_data, is_flat=True), for_report]

    def _generate_intensive_scan_single(self, collected_data, max_depth=100, is_flat=True):
        target = collected_data.get("target_data", {})
        try:
            t_id = int(target.get("target_id", 0))
            start_ns = int(target.get("start_ts_ns", 0))
            dur_ns = int(target.get("duration_ns", 0))
            end_ns = start_ns + dur_ns
        except (ValueError, TypeError):
            self.output_callback("🚨 [Error] Invalid target data format.", True)
            return None

        # 1. 루트(Target) 정보 조회
        query = f"SELECT s.name, tt.utid FROM slice s JOIN thread_track tt ON s.track_id = tt.id WHERE s.id = {t_id}"
        res = self._common_api.tp_s.query(query).as_pandas_dataframe()
        if res.empty: return None

        root_name = res.iloc[0]['name']
        utid_s = int(res.iloc[0]['utid'])

        # 2. 기준 지연 확정
        s_metrics = self._get_node_metrics_by_id(self._common_api.tp_s, utid_s, t_id, start_ns, end_ns)
        total_case_duration = s_metrics['dur']

        self.output_callback(f"🎯 [Investigation Started] {root_name} | Baseline Latency: {total_case_duration:.1f}ms", True)

        if is_flat:
            candidates = []
            # 루트 노드는 parent_id가 없음
            root_info = self._get_processed_node_data(t_id, root_name, utid_s, 1, total_case_duration, [start_ns, end_ns], parent_id=None)
            if root_info:
                self._trace_inheritance_recursive(root_info, utid_s, 2, max_depth, total_case_duration, [start_ns, end_ns], candidates)
            return {
                "investigation_context": {
                    "milestone_name": root_name, 
                    "total_delta": round(total_case_duration, 1)
                }, 
                "candidates": candidates
            }
        else:
            return self._build_recursive_node_pro(t_id, root_name, utid_s, 1, max_depth, total_case_duration, [start_ns, end_ns])

    def _get_processed_node_data(self, slice_id, name, utid, depth, total_case_dur, bounds_s, parent_id=None):
        s_metrics = self._get_node_metrics_by_id(self._common_api.tp_s, utid, slice_id, bounds_s[0], bounds_s[1])
        delta = round(s_metrics['dur'], 1)
        if delta <= 0: return None
        
        self_val = round(s_metrics['self'], 1)
        wait_val = round(s_metrics['wait'], 1)
        
        # 자식들의 Delta 합계 계산
        query = f"SELECT id, dur FROM slice WHERE parent_id = {slice_id}"
        c_res = self._common_api.tp_s.query(query).as_pandas_dataframe()
        children_sum_delta = (c_res['dur'].sum() or 0) / 1e6

        # Ghost Gap 계산
        g_gap = round(max(0, delta - children_sum_delta - self_val), 1)
        impact_ratio = round(delta / total_case_dur, 3) if total_case_dur > 0 else 0

        return {
            "slice_id": int(slice_id),
            "parent_id": int(parent_id) if parent_id is not None else None,
            "name": name,
            "depth": depth,
            "delta_time": delta, 
            "self_time": self_val,
            "wait_time": wait_val,
            "ghost_gap": g_gap,
            "children_sum_delta": round(children_sum_delta, 1),
            "impact_ratio": impact_ratio,
            "is_leaf": (len(c_res) == 0)
        }

    def _trace_inheritance_recursive(self, parent_info, utid, depth, max_depth, total_case_dur, bounds_s, out_list):
        """상속 경로를 따라가며 지연의 근원지를 추적합니다."""
        if depth > max_depth: return

        children_df = self._get_structural_children(self._common_api.tp_s, parent_info['slice_id'])
        if children_df.empty:
            out_list.append(parent_info); return

        total_children_delta = children_df['dur'].sum() / 1e6
        group_ratio = total_children_delta / parent_info['delta_time'] if parent_info['delta_time'] > 0 else 0

        if group_ratio >= self.INHERITANCE_THRESHOLD:
            top_child_row = children_df.iloc[0]
            top_child_info = self._get_processed_node_data(
                top_child_row['id'], top_child_row['name'], utid, depth, 
                total_case_dur, bounds_s, parent_id=parent_info['slice_id']
            )

            # Spamming 감지 (자식들 합은 큰데 1등 자식이 독보적이지 않을 때)
            if top_child_info and (top_child_info['delta_time'] / parent_info['delta_time']) < self.INHERITANCE_THRESHOLD:
                parent_info['reason'] = "Sequential_Spamming_Detected"
                parent_info['sequential_children_count'] = len(children_df)
                out_list.append(parent_info)
            elif top_child_info:
                self._trace_inheritance_recursive(top_child_info, utid, depth + 1, max_depth, total_case_dur, bounds_s, out_list)
        else:
            out_list.append(parent_info)

    def _get_node_metrics_by_id(self, tp, utid, slice_id, start_ts, end_ts):
        """커널 스레드 상태를 분석하여 실제 Running/Wait 시간을 분리합니다."""
        query = f"SELECT ts, dur FROM slice WHERE id = {slice_id}"
        res = tp.query(query).as_pandas_dataframe()
        if res.empty: return {'dur': 0, 'self': 0, 'wait': 0}
        
        s_ts, s_dur = res.iloc[0]['ts'], res.iloc[0]['dur']
        a_start, a_end = max(s_ts, start_ts), min(s_ts + s_dur, end_ts)
        a_dur_ns = max(0, a_end - a_start)

        if a_dur_ns <= 0: return {'dur': 0, 'self': 0, 'wait': 0}

        st_query = f"""
            SELECT state, SUM(CASE 
                WHEN ts < {a_start} THEN ts + dur - {a_start}
                WHEN ts + dur > {a_end} THEN {a_end} - ts
                ELSE dur END) as clipped_ns
            FROM thread_state WHERE utid = {utid} AND ts + dur > {a_start} AND ts < {a_end} GROUP BY 1
        """
        st_res = tp.query(st_query).as_pandas_dataframe()
        running_ms = st_res[st_res['state'].isin(['Running', 'Run'])]['clipped_ns'].sum() / 1e6
        wait_ms = st_res[st_res['state'].isin(['R', 'D', 'DK', 'S'])]['clipped_ns'].sum() / 1e6
        
        return {'dur': round(a_dur_ns / 1e6, 2), 'self': round(running_ms, 2), 'wait': round(wait_ms, 2)}

    def _get_structural_children(self, tp, parent_id):
        return tp.query(f"SELECT id, name, ts, dur FROM slice WHERE parent_id = {parent_id} ORDER BY dur DESC").as_pandas_dataframe()

    def _build_recursive_node_pro(self, slice_id, name, utid, depth, max_depth, total_case_dur, bounds_s, parent_id=None):
        """Tree 모드 전용 (계층 구조 보존)"""
        node_info = self._get_processed_node_data(slice_id, name, utid, depth, total_case_dur, bounds_s, parent_id)
        if not node_info or depth > max_depth: return None

        node_data = {**node_info, "children": []}
        children_df = self._get_structural_children(self._common_api.tp_s, slice_id)
        
        for _, child in children_df.iterrows():
            child_node = self._build_recursive_node_pro(
                child['id'], child['name'], utid, depth + 1, 
                max_depth, total_case_dur, bounds_s, parent_id=slice_id
            )
            if child_node: node_data["children"].append(child_node)
        return node_data

    def summarize_investigation(self, app_package, selected_milestone_info, flat_data, full_data):
        candidates = flat_data.get("candidates", [])
        if not candidates:
            return None

        # 1. 기준점 설정 (마일스톤 전체 지연)
        # investigation_context에 total_delta가 저장되어 있다고 가정합니다.
        range_name = f"{selected_milestone_info['start_name']} ~ {selected_milestone_info['end_name']}"
        milestone_delay = selected_milestone_info["total_delay_ms"]

        total_delta = flat_data.get("investigation_context", {}).get("total_delta", 0)
        if total_delta == 0:
            total_delta = candidates[0].get('delta', 0) # 백업용

        root_node = candidates[0] # 첫 번째 후보가 항상 루트(발원지)

        # 2. 죄목별 합산 (고유 지연량 합산)
        # Self와 Ghost는 각 노드에서 발생한 고유 지연이므로 모두 더합니다.
        total_self = sum(c.get('self_time', 0) for c in candidates)
        total_ghost = sum(c.get('ghost_gap', 0) for c in candidates)
        
        # Wait는 루트의 Wait가 전체 지연의 천장(Limit)입니다.
        total_wait = root_node.get('wait_time', 0)

        # 3. 은닉된 대기(Hidden Wait) 산출
        # 루트가 기다린 시간 중 자식들의 대기 시간으로 설명되지 않는 공백
        children_wait_sum = sum(c.get('wait_time', 0) for c in candidates[1:])
        hidden_wait = round(max(0, total_wait - children_wait_sum), 1)

        # 노멀라이즈 수행 (합계를 100으로 고정) 
        app_raw = round(total_self / total_delta, 2) if total_delta > 0 else 0
        sys_raw = round((total_wait + total_ghost) / total_delta, 2) if total_delta > 0 else 0
        total_raw = app_raw + sys_raw
        if total_raw > 0:
            app_norm = round((app_raw / total_raw) * 100, 1)
            sys_norm = round((sys_raw / total_raw) * 100, 1)
        else:
            app_norm, sys_norm = 0.0, 0.0

        # 4. 최종 JSON 패키징
        return {
            "metadata": {
                "app_name": app_package,
                "milestone_range": range_name,
                "total_delay_delta_ms": round(milestone_delay, 1),
                "investigation_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            
            "final_verdict": {
                "comment": "책임 소재 판결 및 지연 요약",
                "responsibility_ratio": {
                    "app": app_norm,
                    "system": sys_norm
                },
                "delay_summary_ms": {
                    "pure_app_self": round(total_self, 1),
                    "explicit_system_wait": round(total_wait, 1),
                    "scheduling_ghost_gap": round(total_ghost, 1),
                    "hidden_system_wait_mystery": hidden_wait
                }
            },

            # 요약된 용의자 명단 (Flat Tree 결과물)
            "prime_suspects_flat": candidates,

            # 리얼 전수조사 증거물 (Full Tree 전체 구조)
            "evidence_room_full_tree": full_data
        }