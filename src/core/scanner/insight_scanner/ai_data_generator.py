import datetime
import pandas as pd
import numpy as np
import sqlite3
from typing import List, Dict, Any, Optional

class AIDataGenerator:
    def __init__(self, slice_info_list: List[Dict[str, Any]]):
        self.db_path = "C:\\Users\\cjfty\\Downloads\\trace-sun-BP2A.250605.031.A3-2026-03-28-00-25-10.perfetto-trace.db"
        try:
            self.tp = sqlite3.connect(self.db_path, check_same_thread=False)
        except Exception as e:
            return

        self.slice_info_list = slice_info_list
        self.slice_names = [item['name'] for item in slice_info_list]

        bounds = self._get_bounds(self.slice_names)
        print("asdasd2222")
        if not bounds:
            self.start_ns = self.end_ns = None
            self.all_utids = []
            self.utid = -1
            return

        self.start_ns, self.end_ns, self.all_utids, self.slice_ids = bounds
        self.utid = self.all_utids[0] if self.all_utids else -1

        self.df_slices = pd.DataFrame()
        self.df_states = pd.DataFrame()
        self.df_children_map = {}

        self._preload_massive_data()
        print("asdasd")

        print(self.summary_context())

    def query_to_df(self, sql: str, params: Optional[List[Any]] = None) -> pd.DataFrame:
        return pd.read_sql_query(sql, self.tp, params=params or [])

    def _get_bounds(self, slice_names, margin_time_ms=200):
        if not slice_names: return None
        placeholders = ",".join(["?" for _ in slice_names])
        query = f"""
            SELECT 
                MIN(s.ts) as min_ts, 
                MAX(s.ts + s.dur) as max_ts,
                GROUP_CONCAT(DISTINCT a.int_value) as utid_list,
                GROUP_CONCAT(DISTINCT s.id) as slice_id_list
            FROM slice s
            JOIN track t ON s.track_id = t.id
            JOIN args a ON t.dimension_arg_set_id = a.arg_set_id
            WHERE s.name IN ({placeholders}) AND a.key = 'utid'
        """
        res = self.query_to_df(query, slice_names)
        if res.empty or pd.isnull(res.iloc[0]['min_ts']): return None

        utid_list = [int(x) for x in str(res.iloc[0]['utid_list']).split(',')]
        slice_id_list = [int(x) for x in str(res.iloc[0]['slice_id_list']).split(',')]
        
        margin_ns = int(margin_time_ms * 1e6)
        start_ns = max(0, int(res.iloc[0]['min_ts']) - margin_ns)
        end_ns = int(res.iloc[0]['max_ts']) + margin_ns
        return start_ns, end_ns, utid_list, slice_id_list

    def _preload_massive_data(self):
        s_query = """
            SELECT s.id, s.name, s.parent_id, s.ts, s.dur, s.arg_set_id,
                   at.int_value as utid
            FROM slice s
            JOIN track t ON s.track_id = t.id
            LEFT JOIN args at ON t.dimension_arg_set_id = at.arg_set_id AND at.key = 'utid'
            WHERE s.ts >= ? AND s.ts <= ?
        """
        df = self.query_to_df(s_query, [self.start_ns, self.end_ns])
        if not df.empty:
            arg_ids = df['arg_set_id'].unique().tolist()
            if arg_ids:
                p_holders = ",".join(["?" for _ in arg_ids])
                args_query = f"SELECT arg_set_id, key, COALESCE(display_value, string_value, CAST(int_value AS TEXT)) as val FROM args WHERE arg_set_id IN ({p_holders})"
                df_args_raw = self.query_to_df(args_query, arg_ids)
                df_args_combined_raw = df_args_raw.groupby('arg_set_id').apply(
                    lambda x: ", ".join(f"{k}:{v}" for k, v in zip(x['key'], x['val'])), include_groups=False
                )
                df_args_combined_raw.name = 'arguments'
                df_args_combined: Any = df_args_combined_raw.reset_index()
                df = df.merge(df_args_combined, on='arg_set_id', how='left')
            self.df_slices = df.set_index('parent_id', drop=False)
        
        utid_placeholders = ",".join(["?" for _ in self.all_utids])
        st_query = f"SELECT ts, dur, state, cpu, utid FROM thread_state WHERE utid IN ({utid_placeholders}) AND ts < ? AND ts + dur > ?"
        self.df_states = self.query_to_df(st_query, self.all_utids + [self.end_ns, self.start_ns])

    def get_all_reports(self):
        reports = []
        if self.df_slices.empty: return reports
        for s_id in self.slice_ids:
            root_mask = (self.df_slices['id'] == s_id)
            if not root_mask.any(): continue
            root = self.df_slices[root_mask].iloc[0]
            utid_val: Any = root['utid']
            u_id = int(utid_val) if utid_val is not None and not pd.isna(utid_val) else self.utid
            tree = self._build_recursive_node(root['id'], root['name'], u_id, 1, [root['ts'], root['ts'] + root['dur']])
            if tree: reports.append(tree)
        return reports

    def _get_metrics_from_memory(self, utid, a_start, a_end):
        if utid == -1 or self.df_states.empty:
            return {'self': 0, 'wait': 0, 'runnable': 0, 'io': 0, 'mutex': 0, 'cpu': -1}
        mask = (self.df_states['utid'] == utid) & (self.df_states['ts'] + self.df_states['dur'] > a_start) & (self.df_states['ts'] < a_end)
        subset: Any = self.df_states[mask].copy()
        if subset.empty:
            return {'self': 0, 'wait': 0, 'runnable': 0, 'io': 0, 'mutex': 0, 'cpu': -1}
        subset['c_start'] = np.maximum(subset['ts'], a_start)
        subset['c_end'] = np.minimum(subset['ts'] + subset['dur'], a_end)
        
        dur_series: Any = subset['c_end'] - subset['c_start']
        subset['c_dur_ms'] = dur_series.clip(lower=0) / 1e6
        
        top_cpu = -1
        state_mask = subset['state'].isin(['Running', 'R'])
        cpu_mask = subset['cpu'].notnull()
        run_sub: Any = subset[state_mask & cpu_mask]
        
        if not run_sub.empty:
            top_cpu = int(run_sub.sort_values(by='c_dur_ms', ascending=False).iloc[0]['cpu'])
        else:
            valid_cpu: Any = subset[subset['cpu'].notnull()]
            if not valid_cpu.empty: 
                top_cpu = int(valid_cpu.iloc[-1]['cpu'])
                
        return {
            'self': round(float(subset[subset['state'].isin(['Running', 'R'])]['c_dur_ms'].sum()), 2),
            'wait': round(float(subset[subset['state'].isin(['D', 'DK', 'S'])]['c_dur_ms'].sum()), 2),
            'runnable': round(float(subset[subset['state'] == 'R+']['c_dur_ms'].sum()), 2),
            'io': round(float(subset[subset['state'] == 'D']['c_dur_ms'].sum()), 2),
            'mutex': round(float(subset[subset['state'] == 'S']['c_dur_ms'].sum()), 2),
            'cpu': int(top_cpu)
        }

    def _build_recursive_node(self, slice_id, name, utid, depth, bounds):
        if depth > 10: return None
        
        m = self._get_metrics_from_memory(utid, bounds[0], bounds[1])
        delta = round(float((bounds[1] - bounds[0]) / 1e6), 2)
        
        if delta < 0.5: return None

        node_data = {
            "slice_id": int(slice_id),
            "name": name,
            "delta_time": delta,
            "self_time": m['self'],
            "wait_time": m['wait'],
            "origin_hint": self._generate_origin_hint(m),
            "physical_stats": {
                "io_wait_ms": m['io'],
                "runnable_ms": m['runnable'],
                "mutex_wait_ms": m['mutex'],
                "cpu": m['cpu']
            },
            "children": []
        }

        if slice_id in self.df_children_map:
            children_df = self.df_children_map[slice_id]
            
            rel_threshold = delta * 0.15
            abs_threshold = 10.0
            
            mask = ((children_df['dur'] / 1e6) >= rel_threshold) | ((children_df['dur'] / 1e6) >= abs_threshold)
            significant_children = children_df[mask].head(3)
            
            total_children_dur_ms = children_df['dur'].sum() / 1e6
            selected_children_dur_ms = significant_children['dur'].sum() / 1e6
            others_delta = round(max(0.0, float(total_children_dur_ms - selected_children_dur_ms)), 1)

            for _, child in significant_children.iterrows():
                child_utid = int(child['utid']) if pd.notnull(child['utid']) else utid
                child_node = self._build_recursive_node(
                    child['id'], 
                    child['name'], 
                    child_utid, 
                    depth + 1, 
                    [child['ts'], child['ts'] + child['dur']]
                )
                if child_node:
                    node_data["children"].append(child_node)

            if others_delta > 5.0:
                node_data["children"].append({
                    "name": "Minor_Slices_Sum",
                    "delta_time": others_delta
                })
        return node_data

    def _generate_origin_hint(self, m):
        total_wait = m['wait'] + m['runnable']
        if total_wait < 2.0: return "Execution Focus"
        if m['io'] > (total_wait * 0.4): return "Storage/IO Bottleneck"
        if m['mutex'] > (total_wait * 0.4): return "Lock/Mutex Contention"
        if m['runnable'] > (total_wait * 0.5): return "CPU Starvation (Scheduling)"
        return "Logic/IPC Context"

    def get_top_candidates(self, limit=70):
        if self.df_slices.empty: return []
        analysis_df = self.df_slices[self.df_slices['dur'] >= 1e6].copy()
        all_processed = []
        milestone_ids = set(self.slice_ids)
        for _, row in analysis_df.iterrows():
            utid_val: Any = row['utid']
            u_id = int(utid_val) if utid_val is not None and not pd.isna(utid_val) else self.utid
            m = self._get_metrics_from_memory(u_id, row['ts'], row['ts'] + row['dur'])
            delta = round(float(row['dur'] / 1e6), 2)
            badness = delta + (m['wait'] * 2) + (m['runnable'] * 3)
            all_processed.append({
                "slice_id": int(row['id']), "is_milestone": int(row['id']) in milestone_ids, "name": row['name'],
                "delta_time": delta, "self_time": m['self'], "wait_time": m['wait'], "origin_hint": self._generate_origin_hint(m),
                "physical_stats": {"io_wait_ms": m['io'], "runnable_ms": m['runnable'], "mutex_wait_ms": m['mutex'], "cpu": m['cpu']},
                "ts": float(row['ts']), "badness_score": round(float(badness), 2)
            })
        milestones = [n for n in all_processed if n['is_milestone']]
        others = [n for n in all_processed if not n['is_milestone']]
        others_sorted = sorted(others, key=lambda x: x['badness_score'], reverse=True)
        final = milestones + others_sorted[:max(0, limit - len(milestones))]
        return sorted(final, key=lambda x: x['ts'])

    def summary_context(self, app_package="Unknown"):
        milestones_tree = self.get_all_reports()
        timeline_candidates = self.get_top_candidates(limit=70)
        
        start_ns = self.start_ns
        end_ns = self.end_ns
        duration_ms = 0.0
        if start_ns is not None and end_ns is not None:
            duration_ms = round(float((end_ns - start_ns) / 1e6), 2)
            
        return {
            "metadata": {
                "investigation_target": app_package,
                "time_range_ns": {
                    "start": int(start_ns) if start_ns else 0,
                    "end": int(end_ns) if end_ns else 0,
                    "duration_ms": duration_ms
                },
            },
            "deep_dive_reports": milestones_tree,
            "timeline_candidates": timeline_candidates
        }