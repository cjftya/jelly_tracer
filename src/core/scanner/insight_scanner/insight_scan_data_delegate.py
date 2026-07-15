import datetime
import pandas as pd

class InsightScanDataDelegate:
    def __init__(self, event_poster):
        self._common_api = None
        self.event_poster = event_poster
        self.package = None
        # 자식들이 부모 지연의 70% 이상을 점유해야 '의미 있는 상속'으로 간주
        self.INHERITANCE_THRESHOLD = 0.7 
        # Normal 트레이스 대조군 딕셔너리
        self.normal_lookup = {} 

    def init(self, common_api, target_package):
        self._common_api = common_api
        self.package = target_package

    def set_normal_baseline(self, df_normal):
        if df_normal is not None and not df_normal.empty:
            self.normal_lookup = dict(zip(df_normal['name'], df_normal['avg_ms_normal']))

    def fetch_deep_dive_package(self, collected_data):
        # 1. Full Tree 분석 (계층형)
        for_report = self._generate_intensive_scan_single(collected_data, is_flat=False)
        # 2. Candidates 분석 (Flat형)
        return [self._generate_intensive_scan_single(collected_data, is_flat=True), for_report]

    def _generate_intensive_scan_single(self, collected_data, max_depth=100, is_flat=True):
        try:
            t_id = int(collected_data.get("target_id") or 0)
            start_ns = int(collected_data.get("start_ts_ns") or 0)
            dur_ns = int(collected_data.get("duration_ns") or 0)
            end_ns = start_ns + dur_ns
        except (ValueError, TypeError):
            self.event_poster.log("🚨 [Error] Invalid target data format.", True)
            return None

        api = self._common_api
        if not api: return None

        # 1. 루트(Target) 정보 조회
        query = f"SELECT s.name, tt.utid FROM slice s JOIN thread_track tt ON s.track_id = tt.id WHERE s.id = {t_id}"
        res = api.tp_s.query(query).as_pandas_dataframe()
        if res.empty: return None

        root_name = res.iloc[0]['name']
        utid_s = int(res.iloc[0]['utid'])

        # 2. 기준 지연 확정
        s_metrics = self._get_node_metrics_by_id(api.tp_s, utid_s, t_id, start_ns, end_ns)
        total_case_duration = s_metrics['dur']

        self.event_poster.log(f"🎯 [Investigation Started] {root_name} | Baseline: {total_case_duration:.1f}ms", True)

        if is_flat:
            candidates = []
            # Flat 모드: depth와 parent_id 포함
            root_info = self._get_processed_node_data(t_id, root_name, utid_s, 1, [start_ns, end_ns], parent_id=None, is_flat=True)
            if root_info:
                self._trace_inheritance_recursive(root_info, utid_s, 2, max_depth, [start_ns, end_ns], candidates)
            return {
                "investigation_context": {
                    "milestone_name": root_name, 
                    "total_delta": round(total_case_duration, 1)
                }, 
                "candidates": candidates
            }
        else:
            # Tree 모드: depth와 parent_id 제외 (계층 구조로 인지)
            return self._build_recursive_node_pro(t_id, root_name, utid_s, 1, max_depth, [start_ns, end_ns])

    def _get_node_metrics_by_id(self, tp, utid, slice_id, start_ts, end_ts):
        query = f"SELECT ts, dur FROM slice WHERE id = {slice_id}"
        res = tp.query(query).as_pandas_dataframe()
        if res.empty: 
            return {'dur': 0, 'self': 0, 'wait': 0, 'io_ms': 0, 'runnable_ms': 0, 'mutex_ms': 0, 'cpu': -1, 'wchan': None}

        s_ts, s_dur = res.iloc[0]['ts'], res.iloc[0]['dur']
        a_start, a_end = max(s_ts, start_ts), min(s_ts + s_dur, end_ts)
        a_dur_ns = max(0, a_end - a_start)

        if a_dur_ns <= 0: 
            return {'dur': 0, 'self': 0, 'wait': 0, 'io_ms': 0, 'runnable_ms': 0, 'mutex_ms': 0, 'cpu': -1, 'wchan': None}

        columns_info = tp.query("PRAGMA table_info(thread_state)").as_pandas_dataframe()
        has_wchan = 'wchan' in columns_info['name'].values
        wchan_col = "wchan," if has_wchan else "NULL as wchan,"

        st_query = f"""
            SELECT state, cpu, {wchan_col} SUM(CASE 
                WHEN ts < {a_start} THEN ts + dur - {a_start}
                WHEN ts + dur > {a_end} THEN {a_end} - ts
                ELSE dur END) as clipped_ns
            FROM thread_state 
            WHERE utid = {utid} AND ts + dur > {a_start} AND ts < {a_end} 
            GROUP BY 1, 2, 3
        """
        st_res = tp.query(st_query).as_pandas_dataframe()
        
        # 1. Running: 실제 CPU 점유
        running_ms = st_res[st_res['state'].isin(['Running', 'R'])]['clipped_ns'].sum() / 1e6
        
        # 2. Wait (Blocked): 자원(I/O, Mutex) 때문에 강제로 멈춘 시간 (R+ 제외)
        pure_wait_ms = st_res[st_res['state'].isin(['D', 'DK', 'S'])]['clipped_ns'].sum() / 1e6
        
        # 3. Runnable (Ghost): CPU를 기다린 스케줄링 지연 시간
        runnable_ms = st_res[st_res['state'] == 'R+']['clipped_ns'].sum() / 1e6

        io_ms = st_res[st_res['state'] == 'D']['clipped_ns'].sum() / 1e6
        mutex_ms = st_res[st_res['state'] == 'S']['clipped_ns'].sum() / 1e6
        
        top_wchan = "Unknown"
        if has_wchan:
            d_states = st_res[st_res['state'] == 'D']
            if not d_states.empty:
                top_wchan = d_states.sort_values(by='clipped_ns', ascending=False).iloc[0]['wchan']

        top_cpu = -1
        if not st_res.empty:
            raw_cpu = st_res.sort_values(by='clipped_ns', ascending=False).iloc[0]['cpu']
            if pd.notnull(raw_cpu): top_cpu = int(raw_cpu)

        return {
            'dur': round(a_dur_ns / 1e6, 2), 
            'self': round(running_ms, 2), 
            'wait': round(pure_wait_ms, 2),    # R+가 빠진 순수 blocked 시간
            'io_ms': round(io_ms, 2), 
            'runnable_ms': round(runnable_ms, 2), # Ghost Gap의 정체
            'mutex_ms': round(mutex_ms, 2), 
            'cpu': top_cpu, 
            'wchan': top_wchan
        }

    def _generate_origin_hint(self, m):
        hint = {
            "category": "App_Logic",
            "reason": "Code execution or logic processing",
            "suspect": "Main/Worker Thread",
            "wchan": m['wchan']
        }
        total_non_running = m['wait'] + m['runnable_ms']
        if total_non_running <= 2.0: return hint

        is_storage = m['wchan'] and any(x in m['wchan'].lower() for x in ['f2fs', 'ext4', 'ufshcd', 'block', 'sdcard'])
        if m['io_ms'] > (total_non_running * 0.4) or is_storage:
            hint.update({"category": "Kernel_IO", "reason": "D-state detected in storage stack", "suspect": "UFS/FS Driver"})
        elif m['mutex_ms'] > (total_non_running * 0.4):
            hint.update({"category": "Resource_Contention", "reason": "Mutex Lock or Binder IPC delay", "suspect": "System_Server/Lock"})
        elif m['runnable_ms'] > (total_non_running * 0.5):
            hint.update({"category": "System_Overload", "reason": "CPU starvation (Runnable state)", "suspect": "Kernel Scheduler"})
        return hint

    def _get_processed_node_data(self, slice_id, name, utid, depth, bounds_s, parent_id=None, is_flat=True):
        if slice_id is None: return None
        api = self._common_api
        if not api: return None

        m = self._get_node_metrics_by_id(api.tp_s, utid, slice_id, bounds_s[0], bounds_s[1])
        delta = m['dur']
        if delta <= 0: return None

        data = {
            "slice_id": int(slice_id),
            "name": name,
            "delta_time": delta, 
            "self_time": m['self'],
            "wait_time": m['wait'],
            "ghost_gap": m['runnable_ms'],
            "is_new_in_slow": (name not in self.normal_lookup),
            "origin_hint": self._generate_origin_hint(m),
            "physical_stats": { 
                "io_wait_ms": m['io_ms'],
                "runnable_ms": m['runnable_ms'],
                "mutex_wait_ms": m['mutex_ms'],
                "cpu": m['cpu']
            }
        }
        
        # Flat 리스트일 때만 부모 정보와 깊이 추가
        if is_flat:
            data["parent_id"] = int(parent_id) if parent_id is not None else None
            data["depth"] = depth
            
        return data

    def _build_recursive_node_pro(self, slice_id, name, utid, depth, max_depth, bounds_s, parent_id=None):
        # Tree 모드이므로 is_flat=False
        node_info = self._get_processed_node_data(slice_id, name, utid, depth, bounds_s, parent_id, is_flat=False)
        if not node_info or depth > 10: return None

        node_data = {**node_info, "children": []}
        api = self._common_api
        if not api: return node_data
        children_df = self._get_structural_children(api.tp_s, slice_id)
        if children_df.empty: return node_data

        rel_threshold = node_info['delta_time'] * 0.15
        abs_threshold = 10.0
        
        mask = (children_df['dur'] / 1e6 >= rel_threshold) | (children_df['dur'] / 1e6 >= abs_threshold)
        significant_children = children_df[mask].head(3) 

        others_delta = round(max(0, (children_df['dur'].sum() / 1e6) - (significant_children['dur'].sum() / 1e6)), 1)

        for _, child in significant_children.iterrows():
            child_node = self._build_recursive_node_pro(child['id'], child['name'], utid, depth + 1, max_depth, bounds_s, parent_id=slice_id)
            if child_node: node_data["children"].append(child_node)

        if others_delta > 5.0: 
            node_data["children"].append({"name": "Minor_Slices_Sum", "delta_time": others_delta})
            
        return node_data

    def _trace_inheritance_recursive(self, parent_info, utid, depth, max_depth, bounds_s, out_list):
        if depth > max_depth: return
        api = self._common_api
        if not api: return
        children_df = self._get_structural_children(api.tp_s, parent_info['slice_id'])
        if children_df.empty:
            out_list.append(parent_info); return
        
        if (children_df['dur'].sum() / 1e6) >= (parent_info['delta_time'] * self.INHERITANCE_THRESHOLD):
            top_child = children_df.iloc[0]
            # Flat 모드이므로 is_flat=True
            top_info = self._get_processed_node_data(top_child['id'], top_child['name'], utid, depth, bounds_s, parent_id=parent_info['slice_id'], is_flat=True)
            if top_info:
                out_list.append(top_info)
                self._trace_inheritance_recursive(top_info, utid, depth + 1, max_depth, bounds_s, out_list)
        else:
            out_list.append(parent_info)

    def _get_structural_children(self, tp, parent_id):
        return tp.query(f"SELECT id, name, ts, dur FROM slice WHERE parent_id = {parent_id} ORDER BY dur DESC").as_pandas_dataframe()

    def summarize_investigation(self, app_package, selected_milestone_info, overall_timeline_context, flat_data, full_data):
        candidates = flat_data.get("candidates", [])
        if not candidates: return None

        range_name = f"{selected_milestone_info['start_name']} ~ {selected_milestone_info['end_name']}"
        milestone_delay = selected_milestone_info["total_delay_ms"]
        total_delta = flat_data.get("investigation_context", {}).get("total_delta", 0) or candidates[0].get('delta_time', 0)

        root_node = candidates[0]
        total_self = root_node.get('self_time', 0)
        total_wait = root_node.get('wait_time', 0)
        total_ghost = root_node.get('ghost_gap', 0)
        hidden_wait = round(max(0, total_wait - sum(c.get('wait_time', 0) for c in candidates[1:])), 1)

        return {
            "metadata": {
                "app_name": app_package,
                "milestone_range": range_name,
                "total_delay_delta_ms": round(milestone_delay, 1),
                "investigation_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            "final_verdict": {
                "delay_summary_ms": {
                    "pure_app_self": round(total_self, 1),
                    "explicit_system_wait": round(total_wait, 1),
                    "scheduling_ghost_gap": round(total_ghost, 1),
                    "hidden_system_wait_mystery": hidden_wait
                }
            },
            "prime_suspects_flat": candidates,
            "evidence_room_full_tree": full_data,
            "overall_timeline_context": overall_timeline_context
        }