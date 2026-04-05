import pandas as pd
import numpy as np
import json

class PointScanDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.output_callback = output_callback
        self.milestones_registry = [] 
        self.normal_baseline_cache = None
        self.milestone_marks = []
        pd.set_option('future.no_silent_downcasting', True)

    def init(self, common_api):
        self._common_api = common_api

    def calculate_common_milestones(self):
        targets = ['bindApplication', 'activityStart', 'activityResume', 'VisualComplete']
        
        # 1. 데이터 수집 (Helper)
        def get_ms_dict(mode):
            try:
                tp = self._common_api.get_trace_processor(mode)
                upid = self._common_api.get_upid(mode)
            except AttributeError:
                tp = self._common_api.tp_n if mode == "normal" else self._common_api.tp_s
                upid = self._common_api.upid_n if mode == "normal" else self._common_api.upid_s
            
            if not tp or not upid: return {}
            
            q = f"SELECT name, ts FROM slice WHERE track_id IN (SELECT id FROM thread_track WHERE utid IN (SELECT utid FROM thread WHERE upid={upid})) AND name IN ({str(targets)[1:-1]}) ORDER BY ts ASC"
            res = tp.query(q).as_pandas_dataframe().drop_duplicates('name')
            d = dict(zip(res['name'], res['ts']))
            
            if 'activityResume' in d and 'VisualComplete' not in d:
                vq = f"SELECT MAX(ts + dur) as last FROM slice WHERE track_id IN (SELECT id FROM thread_track WHERE utid IN (SELECT utid FROM thread WHERE upid={upid})) AND (name LIKE 'Choreographer%' OR name LIKE 'doFrame%' OR name='traversal') AND ts > {d['activityResume']}"
                v_res = tp.query(vq).as_pandas_dataframe()
                if not v_res.empty and pd.notnull(v_res['last'].iloc[0]):
                    d['VisualComplete'] = int(v_res['last'].iloc[0])
            return d

        m_n, m_s = get_ms_dict("normal"), get_ms_dict("slow")
        raw_points = sorted([n for n in targets if n in m_n and n in m_s], key=lambda x: m_s[x])
        if len(raw_points) < 2: return None

        # 2. 기준점 설정 및 누적 델타 계산
        base_n, base_s = m_n[raw_points[0]], m_s[raw_points[0]]
        core_milestones = []
        for n in raw_points:
            delta = ((m_s[n] - base_s) - (m_n[n] - base_n)) / 1e6
            core_milestones.append({"name": n, "ts_s": m_s[n], "ts_n": m_n[n], "delta": delta})

        # 전체 양수 지연 합 (분모용)
        self.total_positive_sum = sum(max(0, core_milestones[i+1]['delta'] - core_milestones[i]['delta']) 
                                    for i in range(len(core_milestones)-1))

        # 3. 해상도 결정
        dur_ms = (core_milestones[-1]['ts_s'] - core_milestones[0]['ts_s']) / 1e6
        num_bins = max(100, min(1000, int(dur_ms / 5.0)))

        # [보간 함수] 특정 Slow TS 지점의 누적 지연(delta)을 반환
        def get_interp_delta(target_ts_s):
            if target_ts_s <= core_milestones[0]['ts_s']: return core_milestones[0]['delta']
            if target_ts_s >= core_milestones[-1]['ts_s']: return core_milestones[-1]['delta']
            for i in range(len(core_milestones)-1):
                m1, m2 = core_milestones[i], core_milestones[i+1]
                if m1['ts_s'] <= target_ts_s <= m2['ts_s']:
                    r = (target_ts_s - m1['ts_s']) / (m2['ts_s'] - m1['ts_s'])
                    return m1['delta'] + (m2['delta'] - m1['delta']) * r
            return core_milestones[-1]['delta']

        # ---------------------------------------------------------
        # 4. [데이터 통합] 모든 시간 값과 실제 지연량(ms) 포함
        # ---------------------------------------------------------
        self.milestones_registry = []
        total_range_s = core_milestones[-1]['ts_s'] - core_milestones[0]['ts_s']
        step_s = total_range_s / num_bins

        for i in range(num_bins):
            # Slow 트레이스 시간 (나노초)
            s_ts_start = int(core_milestones[0]['ts_s'] + (i * step_s))
            s_ts_end = int(core_milestones[0]['ts_s'] + ((i + 1) * step_s))
            
            # 보간된 누적 지연값 (ms)
            delta_start = get_interp_delta(s_ts_start)
            delta_end = get_interp_delta(s_ts_end)
            
            # [신규] 해당 구간에서 발생한 순수 지연량 (ms)
            # 0보다 작으면(회복 구간) 수사 가치가 없으므로 0으로 클리핑
            seg_delay_ms = max(0.0, delta_end - delta_start)
            
            # 지연 비율
            ratio = (seg_delay_ms / self.total_positive_sum) if self.total_positive_sum > 0 else 0
            
            # [신규] Normal 트레이스 대응 시간 계산 (나노초)
            # 공식: n_ts = base_n + (s_ts - base_s) - (delta * 1e6)
            n_ts_start = int(base_n + (s_ts_start - base_s) - (delta_start * 1e6))
            n_ts_end = int(base_n + (s_ts_end - base_s) - (delta_end * 1e6))
            
            # 이름 계승 로직
            current_name = "Unknown"
            for m in core_milestones:
                if s_ts_start >= m['ts_s']:
                    current_name = m['name']
                else:
                    break

            self.milestones_registry.append({
                "name": current_name,
                "ts_s_start": s_ts_start,
                "ts_s_end": s_ts_end,
                "ts_n_start": n_ts_start,
                "ts_n_end": n_ts_end,
                "delay_ms": round(seg_delay_ms, 4), # 이 구간의 순수 지연량
                "delay_ratio": round(ratio, 4),
                "status": "HOT" if ratio > 0 else "STABLE"
            })

        self.milestone_marks = core_milestones # 📍 마커용 데이터 별도 보관

        if self.output_callback:
            self.output_callback(f"\n✅ [COMPLETED] {num_bins} segments created with full time-mapping.")

        return self.milestones_registry

    def run_point_scan(self, target_package_name, start_milestone_index, end_milestone_index, coverage_target_ratio=0.8):
        if not self.milestones_registry:
            self.output_callback("🚨 [Error] Milestones have not been initialized.", True)
            return None

        # 1. 수사 범위(Time Window) 확정
        start_milestone_data = self.milestones_registry[start_milestone_index]
        end_milestone_data = self.milestones_registry[end_milestone_index]
        
        scan_range_start_ts_slow = start_milestone_data['ts_s_start']
        scan_range_end_ts_slow = end_milestone_data['ts_s_end']
        scan_range_start_ts_normal = start_milestone_data['ts_n_start']
        scan_range_end_ts_normal = end_milestone_data['ts_n_end']
        
        selected_data = self.milestones_registry[start_milestone_index:end_milestone_index+1]

        # 이 구간의 총 추가 지연 시간(ms)
        total_observed_delay_ms = sum(item['delay_ms'] for item in selected_data)
        self.output_callback(f"Range: {start_milestone_data['name']} ({start_milestone_index}) ~ {end_milestone_data['name']} ({end_milestone_index})", True)
        self.output_callback(f"Total Observed Delay: {total_observed_delay_ms:.1f}ms\n", True)
        
        self.output_callback(f"🔍 [Point-Scan] Investigating {total_observed_delay_ms:.1f}ms delay between {start_milestone_data['name']} and {end_milestone_data['name']}", True)

        self.normal_baseline_cache = self.prepare_normal_baseline(scan_range_start_ts_normal, scan_range_end_ts_normal)

        # 2. 패키지 소속 모든 스레드 식별
        package_thread_map = self._get_threads_by_package()
        if not package_thread_map:
            self.output_callback(f"🚨 [Error] No threads found for package: {target_package_name}", True)
            return None

        # 3. 전수 조사: 모든 스레드에서 지연 후보군 수집
        candidate_incidents = self._collect_delay_candidates_across_threads(
            package_thread_map, 
            scan_range_start_ts_slow, scan_range_end_ts_slow,
            scan_range_start_ts_normal, scan_range_end_ts_normal
        )

        # 4. 독립적인 핵심 사건 선정 (Greedy Selection)
        final_incidents = self._select_independent_worst_incidents(
            candidate_incidents, total_observed_delay_ms, coverage_target_ratio
        )

        # 5. Ghost Gap(설명되지 않은 공백) 계산
        captured_delay_sum_ms = sum(inc['delay_delta_ms'] for inc in final_incidents)
        overlap_factor = round(captured_delay_sum_ms / total_observed_delay_ms, 2) if total_observed_delay_ms > 0 else 0
        unexplained_ghost_ms = max(0, total_observed_delay_ms - captured_delay_sum_ms)
        
        if unexplained_ghost_ms > 10.0 and overlap_factor < 1.0: # 병렬이 아닐 때만 고스트 갭 유의미
            final_incidents.append({
                "slice_id": None, # 실제 슬라이스가 아니므로 ID 없음
                "thread_name": "System/Kernel",
                "slice_name": "Ghost Gap (Unexplained Silence)",
                "delay_delta_ms": round(unexplained_ghost_ms, 2),
                "self_running_ms": 0.0,
                "wait_bottleneck_ms": 0.0,
                "is_ghost_incident": True,
                "start_timestamp": scan_range_start_ts_slow,
                "duration_ns": int(unexplained_ghost_ms * 1e6)
            })
        
        if total_observed_delay_ms > 0:
            self.output_callback(f"✅ [Point-Scan] Found {len(final_incidents)} incidents covering {captured_delay_sum_ms/total_observed_delay_ms:.1%} of delay.", True)
        else:
            self.output_callback(f"✅ [Point-Scan] Found {len(final_incidents)} incidents.", True)

        return {
            "analysis_metadata": {
                "milestone_range": f"{start_milestone_data['name']} ~ {end_milestone_data['name']}",
                "total_delay_ms": round(total_observed_delay_ms, 2),
                "captured_delay_ms": round(captured_delay_sum_ms, 2),
                "coverage_efficiency": round(captured_delay_sum_ms / total_observed_delay_ms, 2) if total_observed_delay_ms > 0 else 0,
                "overlap_factor": overlap_factor,
                "concurrency_mode": "High (Spamming/Parallel)" if overlap_factor > 1.2 else "Low (Sequential)"
            },
            "normal_baseline": self.normal_baseline_cache,
            "incidents": final_incidents
        }

    def prepare_normal_baseline(self, start_ts, end_ts):
        query = f"""
            SELECT DISTINCT name, AVG(dur)/1e6 as avg_ms_normal 
            FROM slice 
            WHERE ts >= {start_ts} AND ts <= {end_ts}
            GROUP BY name
        """
        df_all_normal_names = self._common_api.tp_n.query(query).as_pandas_dataframe()
        return df_all_normal_names

    def _get_threads_by_package(self):
        # common_api에 저장된 slow 트레이스의 upid를 가져옵니다.
        upid = self._common_api.upid_s
        
        if upid is None:
            self.output_callback("🚨 [Error] UPID for slow trace is not initialized.", True)
            return {}

        # 서브쿼리 없이 직접 upid로 필터링합니다.
        query = f"""
            SELECT utid, name 
            FROM thread 
            WHERE upid = {upid}
        """
        
        df = self._common_api.tp_s.query(query).as_pandas_dataframe()
        
        return df.set_index('utid')['name'].to_dict() if not df.empty else {}

    def _collect_delay_candidates_across_threads(self, thread_map, start_s, end_s, start_n, end_n):
        target_utids = ",".join(map(str, thread_map.keys()))
        
        query_slow = f"""
            SELECT s.id, s.name, s.ts, s.dur, t.utid 
            FROM slice s
            JOIN thread_track t ON s.track_id = t.id
            WHERE t.utid IN ({target_utids})
            AND s.ts >= {start_s} AND (s.ts + s.dur) <= {end_s}
            ORDER BY s.dur DESC LIMIT 100
        """
        df_slow = self._common_api.tp_s.query(query_slow).as_pandas_dataframe()
        if df_slow.empty: return []

       # Normal 트레이스 대조군 데이터 확보 (JOIN을 사용하여 성능과 가독성 확보)
        unique_names = df_slow['name'].unique()
        name_filter = ",".join(["'" + n.replace("'", "''") + "'" for n in unique_names])
        
        query_normal = f"""
            SELECT s.name, AVG(s.dur)/1e6 as avg_ms_normal 
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            WHERE t.upid = {self._common_api.upid_n}
            AND s.ts >= {start_n} AND (s.ts + s.dur) <= {end_n}
            AND s.name IN ({name_filter}) 
            GROUP BY 1
        """
        df_normal = self._common_api.tp_n.query(query_normal).as_pandas_dataframe()
        normal_lookup = dict(zip(df_normal['name'], df_normal['avg_ms_normal']))

        incident_candidates = []
        for _, row in df_slow.iterrows():
            slow_ms = row['dur'] / 1e6
            normal_ms = normal_lookup.get(row['name'], 0.0)
            delay_delta = slow_ms - normal_ms
            
            if delay_delta <= 2.0: continue

            # 물리 지표 상세 계산
            metrics = self._calculate_physical_metrics(row['utid'], row['ts'], row['dur'])
            
            incident_candidates.append({
                "slice_id": int(row['id']),
                "thread_name": thread_map.get(row['utid'], "Unknown"),
                "slice_name": row['name'],
                "delay_delta_ms": round(delay_delta, 2),
                "self_running_ms": metrics['running_ms'],
                "wait_bottleneck_ms": metrics['waiting_ms'],
                "start_timestamp": int(row['ts']),
                "duration_ns": int(row['dur']),
                "is_ghost_incident": False
            })
        
        return sorted(incident_candidates, key=lambda x: x['delay_delta_ms'], reverse=True)

    def _calculate_physical_metrics(self, utid, ts, dur_ns):
        query = f"""
            SELECT state, SUM(dur) as dur_ns
            FROM thread_state 
            WHERE utid = {utid} AND ts >= {ts} AND (ts + dur) <= {ts + dur_ns}
            GROUP BY 1
        """
        df = self._common_api.tp_s.query(query).as_pandas_dataframe()
        if df.empty: return {"running_ms": 0.0, "waiting_ms": 0.0}
        
        running_ms = df[df['state'].isin(['Running', 'R'])]['dur_ns'].sum() / 1e6
        waiting_ms = df[df['state'].isin(['R+', 'D', 'DK', 'S'])]['dur_ns'].sum() / 1e6
        
        return {
            "running_ms": round(running_ms, 2),
            "waiting_ms": round(waiting_ms, 2)
        }

    def _select_independent_worst_incidents(self, candidates, total_delay_ms, goal_ratio):
        selected = []
        accumulated_ms = 0
        # 병렬 실행 시 누적 지연은 마일스톤의 수 배가 될 수 있으므로 캡(Cap)을 대폭 완화
        max_accumulated_cap = total_delay_ms * 5.0
        
        for cand in candidates:
            # 종료 조건: 개수 100개 초과 또는 누적 지연이 마일스톤의 5배 초과
            if len(selected) >= 100 or accumulated_ms >= max_accumulated_cap:
                break
            
            is_independent_on_thread = True
            c_start, c_end = cand['start_timestamp'], cand['start_timestamp'] + cand['duration_ns']
            c_utid = cand.get('utid') # collect 단계에서 utid를 넘겨줘야 함

            for sel in selected:
                # 같은 스레드 내에서 시간이 겹치는 경우만 제외 (부모-자식 중복 방지)
                # 스레드가 다르면 시간이 겹쳐도 병렬 실행이므로 포함시킴
                if cand['thread_name'] == sel['thread_name']:
                    s_start, s_end = sel['start_timestamp'], sel['start_timestamp'] + sel['duration_ns']
                    if max(c_start, s_start) < min(c_end, s_end):
                        is_independent_on_thread = False
                        break
            
            if is_independent_on_thread:
                selected.append(cand)
                accumulated_ms += cand['delay_delta_ms']
                
        return selected

    def test_query(self):
        query = """
SELECT name, id, ts, dur FROM slice 
WHERE (
    name GLOB 'APP_*' OR 
    name GLOB 'initAppWoContext' OR 
    name GLOB 'decodeByteArray' OR 
    name GLOB 'decodeCacheThumb' OR 
    name GLOB 'decodeBitmap' OR 
    name GLOB 'loadLibrary' OR 
    name GLOB 'initAppOnBg' OR 
    name GLOB 'initHeavyApiOnBg' OR 
    name GLOB 'LayoutCache*' OR 
    name GLOB 'publishAlbumsData*' OR 
    name GLOB 'query#*' OR 
    name GLOB 'createFakeView'
)
AND track_id IN (
    208, 213, 224, 249, 265, 267, 268, 319, 320, 321, 322, 324, 325, 
    333, 335, 336, 342, 343, 345, 349, 361, 366, 371, 386, 403, 419, 
    421, 460, 467, 470, 472, 564, 832, 842, 988
)
        """
        df = self._common_api.tp_s.query(query).as_pandas_dataframe()
        print(df)
        