import pandas as pd
import numpy as np
import json

class PointScanDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.output_callback = output_callback
        self.milestones_registry = []  # 추출된 공통 마일스톤 저장소
        self.normal_baseline_cache = None
        pd.set_option('future.no_silent_downcasting', True)

    def init(self, common_api):
        self._common_api = common_api

    def get_common_milestones(self):
        core_candidates = ['bindApplication', 'activityStart', 'activityResume']
        
        def fetch_milestones_by_mode(mode):
            try:
                tp = self._common_api.get_trace_processor(mode)
                upid = self._common_api.get_upid(mode)
            except AttributeError:
                tp = self._common_api.tp_n if mode == "normal" else self._common_api.tp_s
                upid = self._common_api.upid_n if mode == "normal" else self._common_api.upid_s
            
            if tp is None or upid is None:
                return {}

            # 1. 코어 마일스톤 쿼리: 프로세스 내 모든 스레드 대상
            milestone_query = f"""
                SELECT name, ts 
                FROM slice 
                WHERE track_id IN (
                    SELECT id FROM thread_track 
                    WHERE utid IN (SELECT utid FROM thread WHERE upid = {upid})
                )
                AND name IN ({','.join([f"'{name}'" for name in core_candidates])})
                ORDER BY ts ASC
            """
            milestone_df = tp.query(milestone_query).as_pandas_dataframe()
            # 이름 중복 시 가장 먼저 나타난 타임스탬프 선택
            milestone_dict = {row['name']: row['ts'] for _, row in milestone_df.drop_duplicates('name').iterrows()}
            
            # 2. VisualComplete (화면 변화 종료 지점) 탐색
            base_reference_ts = milestone_dict.get('activityResume', 0)
            visual_idle_query = f"""
                SELECT MAX(ts + dur) as last_visual_ts
                FROM slice
                WHERE track_id IN (
                    SELECT id FROM thread_track 
                    WHERE utid IN (SELECT utid FROM thread WHERE upid = {upid})
                )
                AND (name LIKE 'Choreographer%' OR name LIKE 'doFrame%' OR name = 'traversal')
                AND ts > {base_reference_ts}
            """
            visual_df = tp.query(visual_idle_query).as_pandas_dataframe()
            
            if not visual_df.empty:
                last_ts_value = visual_df['last_visual_ts'].iloc[0]
                if pd.notnull(last_ts_value):
                    milestone_dict['VisualComplete'] = int(last_ts_value)
            
            return milestone_dict

        # 양측 데이터 수집
        milestones_normal = fetch_milestones_by_mode("normal")
        milestones_slow = fetch_milestones_by_mode("slow")

        potential_names = core_candidates + ['VisualComplete']
        common_milestone_names = [name for name in potential_names if name in milestones_normal and name in milestones_slow]

        if not common_milestone_names:
            return None

        base_ts_normal = milestones_normal[common_milestone_names[0]]
        base_ts_slow = milestones_slow[common_milestone_names[0]]

        final_milestones = []
        prev_slow_ts = None
        prev_accumulated_delta = 0

        for name in potential_names:
            if name in milestones_normal and name in milestones_slow:
                curr_slow_ts = milestones_slow[name]
                curr_normal_ts = milestones_normal[name]
                
                # 1. 벽시계 시간(Wall-clock) 및 누적 지연 계산
                elapsed_ms_s = (curr_slow_ts - base_ts_slow) / 1e6
                elapsed_ms_n = (curr_normal_ts - base_ts_normal) / 1e6
                accumulated_delta = elapsed_ms_s - elapsed_ms_n

                # 2. [신뢰도 핵심] 구간 내 리소스 워크로드 및 병렬성 계산
                interval_workload_ms = 0
                concurrency_factor = 1.0
                interval_wall_clock = 0
                
                if prev_slow_ts is not None:
                    # 해당 구간(이전 마일스톤 ~ 현재) 동안 발생한 모든 슬라이스 합계(Total Workload)
                    workload_query = f"""
                        SELECT SUM(dur) / 1e6 as total_ms
                        FROM slice
                        WHERE track_id IN (
                            SELECT id FROM thread_track 
                            WHERE utid IN (SELECT utid FROM thread WHERE upid = {self._common_api.upid_s})
                        )
                        AND ts >= {prev_slow_ts} AND ts < {curr_slow_ts}
                    """
                    res_df = self._common_api.tp_s.query(workload_query).as_pandas_dataframe()
                    interval_workload_ms = res_df['total_ms'].iloc[0] if not res_df.empty else 0
                    
                    # 현재 구간의 순수 흐른 시간 (Wall-clock)
                    interval_wall_clock = (curr_slow_ts - prev_slow_ts) / 1e6
                    
                    # 병렬성 지수 (총 작업량 / 흐른 시간)
                    if interval_wall_clock > 0:
                        concurrency_factor = round(interval_workload_ms / interval_wall_clock, 1)

                # 현재 구간만의 지연(Interval Delta)
                interval_delay = accumulated_delta - prev_accumulated_delta

                final_milestones.append({
                    "name": name,
                    "ts_n": curr_normal_ts,
                    "ts_s": curr_slow_ts,
                    "delta_ms": round(accumulated_delta, 2), # 누적 지연
                    "interval_delay": round(interval_delay, 2), # 구간 지연 (대시보드 수치)
                    "elapsed_ms_s": round(elapsed_ms_s, 2),
                    "workload_ms": round(interval_workload_ms, 1), # 총 작업 합계 (300ms 등)
                    "concurrency": concurrency_factor              # 병렬성 배수 (4.2x 등)
                })
                
                prev_slow_ts = curr_slow_ts
                prev_accumulated_delta = accumulated_delta

        # 분석 로그 출력
        if self.output_callback:
            self.output_callback("\n" + "━"*60)
            self.output_callback("🔍 [POINT SCAN] PERFORMANCE INVESTIGATION TIMELINE")
            self.output_callback("━"*60 + "\n")

            for i, m in enumerate(final_milestones):
                # 1. Milestone Header with Status Indicator
                # Threshold: 30ms for Critical (🔴), otherwise Stable (🟢)
                status = "⚪" if m['elapsed_ms_s'] == 0 else ("🔴" if m['interval_delay'] >= 30 else "🟢")
                self.output_callback(f"{status} {m['name']:<20} | ⏱️ {m['elapsed_ms_s']:>8.1f} ms")

                # 2. Interval Data (Vertical connection logic)
                if i < len(final_milestones) - 1:
                    next_m = final_milestones[i+1]
                    delay = next_m['interval_delay']
                    workload = next_m['workload_ms']
                    concurrency = next_m['concurrency']

                    self.output_callback("   │")
                    # Interval Delay: The actual "Wall-clock" time increase
                    self.output_callback(f"   │── [LATENCY] {delay:>+8.1f} ms") 
                    
                    # Resource Workload: Total sum of slice durations / Parallelism
                    if workload > 0:
                        self.output_callback(f"   │── [LOAD   ] {workload:>8.1f} ms_work ({concurrency}x parallel)")
                    
                    self.output_callback("   │")

            self.output_callback("\n" + "━"*60)
            self.output_callback("⚖️ [VERDICT]: Investigate 🔴 sections with high LOAD for optimization.")
            self.output_callback("━"*60)

        self.milestones_registry = final_milestones
        return self.milestones_registry

    def run_point_scan(self, target_package_name, start_milestone_index, end_milestone_index, coverage_target_ratio=0.8):
        if not self.milestones_registry:
            self.output_callback("🚨 [Error] Milestones have not been initialized.", True)
            return None

        # 1. 수사 범위(Time Window) 확정
        start_milestone_data = self.milestones_registry[start_milestone_index]
        end_milestone_data = self.milestones_registry[end_milestone_index]
        
        scan_range_start_ts_slow = start_milestone_data['ts_s']
        scan_range_end_ts_slow = end_milestone_data['ts_s']
        scan_range_start_ts_normal = start_milestone_data['ts_n']
        scan_range_end_ts_normal = end_milestone_data['ts_n']
        
        total_observed_delay_ms = end_milestone_data['delta_ms'] - start_milestone_data['delta_ms']
        
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

        self.output_callback(f"✅ [Point-Scan] Found {len(final_incidents)} incidents covering {captured_delay_sum_ms/total_observed_delay_ms:.1%} of delay.", True)

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
        """thread_state를 분석하여 실제 Running과 Waiting 시간을 분리합니다."""
        query = f"""
            SELECT state, SUM(dur) as dur_ns
            FROM thread_state 
            WHERE utid = {utid} AND ts >= {ts} AND (ts + dur) <= {ts + dur_ns}
            GROUP BY 1
        """
        df = self._common_api.tp_s.query(query).as_pandas_dataframe()
        if df.empty: return {"running_ms": 0.0, "waiting_ms": 0.0}
        
        running_ms = df[df['state'].isin(['Running', 'R'])]['dur_ns'].sum() / 1e6
        waiting_ms = df[df['state'].isin(['R', 'D', 'DK', 'S'])]['dur_ns'].sum() / 1e6
        
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
            # 종료 조건: 개수 3개 초과 또는 누적 지연이 마일스톤의 5배 초과
            if len(selected) >= 3 or accumulated_ms >= max_accumulated_cap:
                break
            
            is_independent_on_thread = True
            c_start, c_end = cand['start_timestamp'], cand['start_timestamp'] + cand['duration_ns']
            c_utid = cand.get('utid') # collect 단계에서 utid를 넘겨줘야 함

            for sel in selected:
                # [핵심 로직] 같은 스레드 내에서 시간이 겹치는 경우만 제외 (부모-자식 중복 방지)
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