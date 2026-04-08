import pandas as pd
import numpy as np

class AIDataGenerator:
    def __init__(self, common_api, slice_info_list):
        self.tp = common_api.tp_s
        self.slice_info_list = slice_info_list
        self.slice_ids = [item['id'] for item in slice_info_list]
        
        bounds = self._get_bounds(self.slice_ids)
        if not bounds:
            self.start_ns = self.end_ns = None
            self.all_utids = []
            self.utid = -1
            return

        self.start_ns, self.end_ns, self.all_utids = bounds
        self.utid = self.all_utids[0] if self.all_utids else -1
        
        self.df_slices = pd.DataFrame()
        self.df_states = pd.DataFrame()

        self._preload_massive_data()

        asd = self.summary_context()

    def _get_bounds(self, slice_ids, margin_time_ms=200):
        if not slice_ids: return None

        ids_str = ",".join(map(str, slice_ids))
        query = f"""
            SELECT 
                MIN(s.ts) as min_ts, 
                MAX(s.ts + s.dur) as max_ts,
                GROUP_CONCAT(DISTINCT tt.utid) as utid_list
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            WHERE s.id IN ({ids_str})
        """
        res = self.tp.query(query).as_pandas_dataframe()
        
        if res.empty or pd.isnull(res.iloc[0]['min_ts']) or pd.isnull(res.iloc[0]['utid_list']):
            return None

        utid_list = [int(x) for x in str(res.iloc[0]['utid_list']).split(',')]
        margin_ns = int(margin_time_ms * 1e6)
        start_ns = max(0, int(res.iloc[0]['min_ts']) - margin_ns)
        end_ns = int(res.iloc[0]['max_ts']) + margin_ns
        
        return start_ns, end_ns, utid_list

    def _preload_massive_data(self):
        s_query = f"""
            SELECT s.id, s.name, s.parent_id, s.ts, s.dur, s.track_id, tt.utid
            FROM slice s
            LEFT JOIN thread_track tt ON s.track_id = tt.id
            WHERE s.ts + s.dur > {self.start_ns} AND s.ts < {self.end_ns}
        """
        raw_slices = self.tp.query(s_query).as_pandas_dataframe()
        if not raw_slices.empty:
            self.df_slices = raw_slices.set_index('parent_id', drop=False)
        else:
            self.df_slices = pd.DataFrame()

        utid_str = ",".join(map(str, self.all_utids))
        st_query = f"""
            SELECT ts, dur, state, cpu, utid
            FROM thread_state 
            WHERE utid IN ({utid_str}) 
              AND ts + dur > {self.start_ns} AND ts < {self.end_ns}
        """
        self.df_states = self.tp.query(st_query).as_pandas_dataframe()

    def get_all_reports(self):
        reports = []
        if self.df_slices.empty: return reports
        for s_id in self.slice_ids:
            root_mask = (self.df_slices['id'] == s_id)
            if not root_mask.any(): continue
            
            root = self.df_slices[root_mask].iloc[0]
            u_id = int(root['utid']) if pd.notnull(root['utid']) else self.utid
            
            tree = self._build_recursive_node(
                root['id'], root['name'], u_id, 1, [root['ts'], root['ts'] + root['dur']]
            )
            if tree: reports.append(tree)
        return reports

    def _get_metrics_from_memory(self, utid, a_start, a_end):
        if utid == -1 or self.df_states.empty:
            return {'self': 0, 'wait': 0, 'runnable': 0, 'io': 0, 'mutex': 0, 'cpu': -1}

        mask = (self.df_states['utid'] == utid) & \
               (self.df_states['ts'] + self.df_states['dur'] > a_start) & \
               (self.df_states['ts'] < a_end)
        
        subset = self.df_states[mask].copy()
        if subset.empty:
            return {'self': 0, 'wait': 0, 'runnable': 0, 'io': 0, 'mutex': 0, 'cpu': -1}

        subset['c_start'] = np.maximum(subset['ts'], a_start)
        subset['c_end'] = np.minimum(subset['ts'] + subset['dur'], a_end)
        subset['c_dur_ms'] = (subset['c_end'] - subset['c_start']).clip(lower=0) / 1e6

        top_cpu = -1
        run_sub = subset[subset['state'].isin(['Running', 'R']) & subset['cpu'].notnull()]
        if not run_sub.empty:
            top_cpu = int(run_sub.sort_values(by='c_dur_ms', ascending=False).iloc[0]['cpu'])
        else:
            valid_cpu = subset[subset['cpu'].notnull()]
            if not valid_cpu.empty: top_cpu = int(valid_cpu.iloc[-1]['cpu'])

        return {
            'self': round(subset[subset['state'].isin(['Running', 'R'])]['c_dur_ms'].sum(), 2),
            'wait': round(subset[subset['state'].isin(['D', 'DK', 'S'])]['c_dur_ms'].sum(), 2),
            'runnable': round(subset[subset['state'] == 'R+']['c_dur_ms'].sum(), 2),
            'io': round(subset[subset['state'] == 'D']['c_dur_ms'].sum(), 2),
            'mutex': round(subset[subset['state'] == 'S']['c_dur_ms'].sum(), 2),
            'cpu': top_cpu
        }

    def _build_recursive_node(self, slice_id, name, utid, depth, bounds):
        if depth > 12: return None
        m = self._get_metrics_from_memory(utid, bounds[0], bounds[1])
        delta = round((bounds[1] - bounds[0]) / 1e6, 2)
        if delta < 0.5: return None

        node = {
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

        if slice_id in self.df_slices.index:
            children = self.df_slices.loc[[slice_id]].sort_values(by='dur', ascending=False)
            threshold = max(delta * 0.1, 2.0)
            for _, child in children.iterrows():
                if (child['dur'] / 1e6) < threshold: continue
                child_utid = int(child['utid']) if pd.notnull(child['utid']) else utid
                child_node = self._build_recursive_node(
                    child['id'], child['name'], child_utid, depth + 1, 
                    [child['ts'], child['ts'] + child['dur']]
                )
                if child_node: node["children"].append(child_node)
        return node

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
            u_id = int(row['utid']) if pd.notnull(row['utid']) else self.utid
            m = self._get_metrics_from_memory(u_id, row['ts'], row['ts'] + row['dur'])
            delta = round(row['dur'] / 1e6, 2)
            badness = delta + (m['wait'] * 2) + (m['runnable'] * 3)
            
            all_processed.append({
                "slice_id": int(row['id']),
                "is_milestone": int(row['id']) in milestone_ids,
                "name": row['name'],
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
                "ts": row['ts'],
                "badness_score": badness
            })
        milestones = [n for n in all_processed if n['is_milestone']]
        others = [n for n in all_processed if not n['is_milestone']]
        others_sorted = sorted(others, key=lambda x: x['badness_score'], reverse=True)
        final = milestones + others_sorted[:max(0, limit - len(milestones))]
        return sorted(final, key=lambda x: x['ts'])

    def _get_regression_analysis(self):
        regression_data = []
        flat_slices = self.df_slices.drop_duplicates('id').set_index('id')
        
        for item in self.slice_info_list:
            s_id = item['id']
            delay = item.get('delay_ms', 0)
            
            if s_id in flat_slices.index:
                row = flat_slices.loc[s_id]
                current_ms = round(row['dur'] / 1e6, 2)
                regression_data.append({
                    "id": s_id,
                    "name": row['name'],
                    "current_ms": current_ms,
                    "regression_delta_ms": delay
                })
        return regression_data

    def summary_context(self, app_package="Unknown"):
        milestones_tree = self.get_all_reports()
        timeline_candidates = self.get_top_candidates(limit=70)
        regression_analysis = self._get_regression_analysis()

        if not milestones_tree and not timeline_candidates:
            return None

        return {
            "metadata": {
                "investigation_target": app_package,
                "time_range_ns": {
                    "start": self.start_ns,
                    "end": self.end_ns,
                    "duration_ms": round((self.end_ns - self.start_ns) / 1e6, 2)
                },
            },
            "regression_analysis": regression_analysis,
            "deep_dive_reports": milestones_tree,
            "system_timeline_context": timeline_candidates
        }