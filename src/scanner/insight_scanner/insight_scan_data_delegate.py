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
        for_report = self._generate_intensive_scan_single(collected_data, is_flat=False)
        return [self._generate_intensive_scan_single(collected_data, is_flat=True), for_report]

    def _generate_intensive_scan_single(self, collected_data, max_depth=6, culling_threshold=0.05, is_flat=True):
        target = collected_data.get("target_data", {})
        try:
            t_id = int(target.get("target_id", 0))
            start_ns = int(target.get("start_ts_ns", 0))
            dur_ns = int(target.get("duration_ns", 0))
            end_ns = start_ns + dur_ns
        except (ValueError, TypeError):
            self.output_callback("🚨 [Error] Invalid numeric data in collected_data.", True)
            return None

        # 1. 루트 정보 조회
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

        # 2. 기준 시간 확정
        s_metrics = self._get_node_metrics_by_id(self._common_api.tp_s, utid_s, t_id, start_ns, end_ns)
        total_case_duration = s_metrics['dur']

        self.output_callback(f"🎯 [Target Locked] {root_name} (ID: {t_id}) | Total Duration: {total_case_duration:.1f}ms", True)

        if is_flat:
            candidates = []
            self._collect_flat_candidates_recursive(
                parent_id=t_id, 
                utid=utid_s, 
                depth=2, 
                max_depth=max_depth, 
                total_case_dur=total_case_duration, 
                bounds_s=[start_ns, end_ns], 
                threshold=culling_threshold,
                out_list=candidates
            )
            
            return {
                "investigation_context": {
                    "milestone_name": root_name,
                    "target_slice_id": t_id,
                    "total_delta_time": round(total_case_duration, 1),
                    "mode": "flat_candidates_only"
                },
                "candidates": candidates
            }
        else:
            # 트리 모드는 계층 구조를 생성하므로 children 필드가 포함됨
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

    def _get_processed_node_data(self, slice_id, name, utid, depth, total_case_dur, bounds_s, parent_id=None):
        """
        [공통 데이터 추출기]
        주의: 여기서는 'children' 필드를 생성하지 않습니다.
        """
        s_metrics = self._get_node_metrics_by_id(self._common_api.tp_s, utid, slice_id, bounds_s[0], bounds_s[1])
        
        delta = round(s_metrics['dur'], 1)
        if delta <= 0: return None
        
        self_val = round(s_metrics['self'], 1)
        wait_val = round(s_metrics['wait'], 1)
        impact_ratio = round(delta / total_case_dur, 3) if total_case_dur > 0 else 0

        query = f"SELECT COUNT(*) as c_count, SUM(dur) as c_sum FROM slice WHERE parent_id = {slice_id}"
        c_res = self._common_api.tp_s.query(query).as_pandas_dataframe()
        c_count = int(c_res.iloc[0]['c_count'])
        children_total_delta = (c_res.iloc[0]['c_sum'] or 0) / 1e6

        g_gap = round(max(0, delta - children_total_delta - self_val), 1)

        native_patterns = r"Native|JNI|0x|postAndWait|acquire|wait|lock|monitor|Sync|Binder|ioctl"
        is_pattern_match = bool(re.search(native_patterns, name, re.IGNORECASE))

        return {
            "slice_id": int(slice_id),
            "name": name,
            "depth": depth,
            "parent_id": int(parent_id) if parent_id else None,
            "delta_time": delta, 
            "self_time": self_val,
            "wait_time": wait_val,
            "impact_ratio": impact_ratio,
            "ghost_gap": g_gap,
            "is_leaf": (c_count == 0),
            "is_native_cliff": (c_count == 0) and (self_val >= 5.0) and is_pattern_match,
            "is_resource_contention": (wait_val / delta > 0.8) if delta > 0 else False,
            "has_ghost_gap": g_gap > 5.0
        }

    def _collect_flat_candidates_recursive(self, parent_id, utid, depth, max_depth, total_case_dur, bounds_s, threshold, out_list):
        if depth > max_depth:
            return

        children_df = self._get_structural_children(self._common_api.tp_s, parent_id)
        
        for _, child in children_df.iterrows():
            c_id = int(child['id'])
            c_name = child['name']
            
            node_info = self._get_processed_node_data(c_id, c_name, utid, depth, total_case_dur, bounds_s, parent_id)
            
            if node_info:
                # ✅ Flat 모드이므로 'children' 필드가 없는 상태로 리스트에 담김
                if node_info["impact_ratio"] >= threshold:
                    out_list.append(node_info)
                
                self._collect_flat_candidates_recursive(
                    c_id, utid, depth + 1, max_depth, total_case_dur, bounds_s, threshold, out_list
                )

    def _build_recursive_node_pro(self, slice_id, name, utid, depth, max_depth, total_case_dur, bounds_s, threshold):
        """Tree 모드 빌더: 계층 구조 형성을 위해 children 필드를 동적으로 추가"""
        node_info = self._get_processed_node_data(slice_id, name, utid, depth, total_case_dur, bounds_s)
        if not node_info or depth > max_depth:
            return None

        # ✅ Tree 모드에서는 children 필드를 추가하여 구조 형성
        node_data = {**node_info, "children": []}
        
        children_df = self._get_structural_children(self._common_api.tp_s, slice_id)
        for _, child in children_df.iterrows():
            child_node = self._build_recursive_node_pro(
                child['id'], child['name'], utid, depth + 1, 
                max_depth, total_case_dur, bounds_s, threshold
            )
            if child_node:
                node_data["children"].append(child_node)

        # 가지치기 조건
        if node_data["impact_ratio"] < threshold and not node_data["children"] and depth > 1:
            return None

        return node_data

    def _get_node_metrics_by_id(self, tp, utid, slice_id, start_ts=None, end_ts=None):
        query = f"SELECT ts, dur FROM slice WHERE id = {slice_id}"
        res = tp.query(query).as_pandas_dataframe()
        if res.empty: return {'dur': 0, 'self': 0, 'wait': 0}
        
        s_ts, s_dur = res.iloc[0]['ts'], res.iloc[0]['dur']
        a_start = max(s_ts, start_ts) if start_ts is not None else s_ts
        a_end = min(s_ts + s_dur, end_ts) if end_ts is not None else s_ts + s_dur
        a_dur_ns = max(0, a_end - a_start)

        if a_dur_ns <= 0: return {'dur': 0, 'self': 0, 'wait': 0}

        st_query = f"""
            SELECT state, SUM(CASE 
                WHEN ts < {a_start} THEN ts + dur - {a_start}
                WHEN ts + dur > {a_end} THEN {a_end} - ts
                ELSE dur END) as clipped_ns
            FROM thread_state 
            WHERE utid = {utid} AND ts + dur > {a_start} AND ts < {a_end}
            GROUP BY 1
        """
        st_res = tp.query(st_query).as_pandas_dataframe()
        
        running_ms = st_res[st_res['state'].isin(['Running', 'Run'])]['clipped_ns'].sum() / 1e6
        wait_ms = st_res[st_res['state'].isin(['R', 'D', 'DK', 'S'])]['clipped_ns'].sum() / 1e6
        
        return {
            'dur': round(a_dur_ns / 1e6, 2),
            'self': round(running_ms, 2),
            'wait': round(wait_ms, 2)
        }

    def _get_structural_children(self, tp, parent_id):
        query = f"SELECT id, name, ts, dur FROM slice WHERE parent_id = {parent_id} ORDER BY dur DESC"
        return tp.query(query).as_pandas_dataframe()