import pandas as pd
import numpy as np
from common_api import CommonAPI

class PointScanDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.utid_n = None
        self.utid_s = None
        self.output_callback = output_callback
        self.num_cpus = 8  # 기본값, init에서 동적 업데이트
        self.pivot_candidates = [] # 예비 후보군 저장소

    def init(self, trace_normal, trace_slow, target_package):
        self._common_api = CommonAPI(trace_normal, trace_slow, target_package)
        
        # 시스템 코어 수 미리 파악 (CPU Load 계산 오버헤드 방지)
        try:
            res = self._common_api.tp_s.query("SELECT MAX(cpu) + 1 FROM sched").as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                self.num_cpus = int(res.iloc[0, 0])
        except Exception:
            self.num_cpus = 8

    def identify_targets(self):
        self.output_callback("🔍 [Targeting] Identifying primary investigation targets...", True)

        res_n = self.get_thread_candidates(self._common_api.tp_n, self._common_api.upid_n)
        res_s = self.get_thread_candidates(self._common_api.tp_s, self._common_api.upid_s)

        if res_n is None or res_s is None:
            missing = "NORMAL" if res_n is None else "SLOW"
            if res_n is None and res_s is None: missing = "BOTH"
            self.output_callback(f"🚨 [CRITICAL] Package data not found in {missing} trace.", True)
            return None, None, None

        # Slow 트레이스에서 지연의 핵심 주범(1위) 선택
        target_row_s = res_s.iloc[0]
        self.target_thread = target_row_s['thread_name']
        self.utid_s = int(target_row_s['utid'])

        # Normal 트레이스에서 동일 이름 스레드 매칭
        match_n = res_n[res_n['thread_name'] == self.target_thread]

        if not match_n.empty:
            self.utid_n = int(match_n.iloc[0]['utid'])
            self.output_callback(f"🎯 [Target Locked] {self.target_thread} (Name Matched)", True)
        else:
            # Fallback: 이름 불일치 시 활동성 기반 강제 매칭
            target_row_n = res_n.iloc[0]
            self.utid_n = int(target_row_n['utid'])
            self.output_callback(f"⚠️ [NOTICE] Thread name mismatch. Matching by activity score.", True)
            self.output_callback(f"   - (N): {target_row_n['thread_name']} <-> (S): {self.target_thread}", True)
        
        return self.utid_n, self.utid_s, self.target_thread

    def generate_cfs(self, utid_n, ts_n, utid_s, ts_s, exclude_scopes=None):
        def get_metrics(tp, utid, ts):
            if ts is None or len(ts) < 2: return "R?,Rn?,S?,D?|L:NoData|C:Unknown"
            duration_ns = ts[1] - ts[0]
            if duration_ns <= 0: return "R0,Rn0,S0,D0|L:None|C:InvalidRange"

            # 1. 스케줄링 상태 및 로드 계산
            query_sched = f"""
                SELECT state, SUM(dur) * 100.0 / ({self.num_cpus} * {duration_ns}) as ratio
                FROM sched WHERE utid = {utid} AND ts >= {ts[0]} AND ts < {ts[1]} GROUP BY state
            """
            states = {'Running': 0, 'R': 0, 'S': 0, 'D': 0}
            try:
                sched_df = tp.query(query_sched).as_pandas_dataframe()
                for _, row in sched_df.iterrows():
                    s = row['state']
                    val = round(row['ratio'], 1)
                    if s == 'Running': states['Running'] = val
                    elif s == 'R': states['R'] = val
                    elif s == 'S': states['S'] = val
                    elif s in ['D', 'DK']: states['D'] = val
            except Exception: pass

            # 2. [Rule B 판단 로직] 시스템 전체 로드(Load) vs 프로세스 내부 경합(ProcLoad)
            # 여기서는 예시로 Running + R 비중이 높으면 Load로 판정하는 로직을 심습니다.
            total_load = states['Running'] + states['R']
            load_tag = "Load" if total_load > 80 else "ProcLoad"
            if total_load < 20: load_tag = "Normal"

            # 3. 주요 슬라이스(L:) 추출
            query_slice = f"""
                SELECT name, SUM(dur)/1e6 as sum_ms FROM slice 
                WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid})
                AND ts >= {ts[0]} AND ts < {ts[1]} GROUP BY 1 ORDER BY 2 DESC LIMIT 5
            """
            try:
                slice_df = tp.query(query_slice).as_pandas_dataframe()
                l_str = ", ".join([f"{r['name']}({r['sum_ms']:.1f}ms)" for _, r in slice_df.iterrows()]) if not slice_df.empty else "No_Slices"
            except Exception: l_str = "Error"

            # 결과 조립: C: 태그 뒤에 load_tag를 붙여 Rule B를 선택하게 함
            return f"R{states['Running']},Rn{states['R']},S{states['S']},D{states['D']}|L:[{l_str}]|C:{load_tag}"

        return (f"### [FORENSIC DATA]\n"
                f"- NORMAL: {get_metrics(self._common_api.tp_n, utid_n, ts_n)}\n"
                f"- SLOW: {get_metrics(self._common_api.tp_s, utid_s, ts_s)}")
    
    def get_thread_candidates(self, tp, upid, global_ts=None):
        if tp is None or upid is None: return None
        ts_filter = f"AND ts >= {global_ts[0]} AND ts < {global_ts[1]}" if global_ts else ""

        # Runnable(R) 뿐만 아니라 D-State(D, DK) 가중치 반영
        query = f"""
            SELECT t.utid, t.name AS thread_name, (
                (CASE WHEN t.name = p.name THEN 150 ELSE 0 END) +
                (CASE WHEN EXISTS (
                    SELECT 1 FROM slice s JOIN thread_track tt ON s.track_id = tt.id
                    WHERE tt.utid = t.utid {ts_filter}
                    AND (s.name LIKE 'Choreographer%' OR s.name LIKE 'doFrame%') LIMIT 1
                ) THEN 250 ELSE 0 END) +
                COALESCE((SELECT SUM(dur)/1e6 FROM thread_state ts 
                    WHERE ts.utid = t.utid 
                    AND ts.state IN ('R', 'D', 'DK') {ts_filter}), 0) * 0.05
            ) AS total_score
            FROM thread t JOIN process p USING(upid)
                WHERE p.upid = {upid} ORDER BY total_score DESC;
            """
        return tp.query(query).as_pandas_dataframe()
        
    def find_worst_slice(self, utid_n, utid_s):
        self.output_callback("🛰️ [Initial Scan] Searching for the most delayed pivot slice...", True)

        dur_n = self.get_total_dur(self._common_api.tp_n)
        dur_s = self.get_total_dur(self._common_api.tp_s)

        query_s = f"""
            SELECT name, SUM(dur)/1e6 as total_ms 
            FROM slice 
            WHERE track_id = (SELECT id FROM thread_track WHERE utid = {utid_s} LIMIT 1)
            AND dur > 0 GROUP BY 1 ORDER BY 2 DESC LIMIT 15
        """
        df_s = self._common_api.tp_s.query(query_s).as_pandas_dataframe()
        if df_s.empty: return None

        worst_slice, max_impact = None, 0
        self.pivot_candidates = [] # 초기화

        for _, row in df_s.iterrows():
            safe_name = row['name'].replace("'", "''")
            slow_ms = row['total_ms']
            slow_ratio = slow_ms / dur_s

            query_n = f"""
                SELECT SUM(dur)/1e6 as total_ms FROM slice 
                WHERE track_id = (SELECT id FROM thread_track WHERE utid = {utid_n} LIMIT 1)
                AND name = '{safe_name}'
            """
            df_n = self._common_api.tp_n.query(query_n).as_pandas_dataframe()
            n_ms_val = df_n.iloc[0]['total_ms'] if not df_n.empty else 0
            n_ms = n_ms_val if pd.notna(n_ms_val) and n_ms_val > 0 else 0.01
            normal_ratio = n_ms / dur_n

            # Impact Score = Ratio * Delta
            ratio = slow_ratio / normal_ratio
            delta_ms = slow_ms - n_ms
            impact_score = ratio * delta_ms

            # 후보군 수집 (일정 수준 이상의 임팩트가 있으면 저장)
            if slow_ms > 5.0 and ratio > 1.2:
                self.pivot_candidates.append({'name': row['name'], 'impact': impact_score})

            if slow_ms > 2.0 and impact_score > max_impact:
                max_impact = impact_score
                worst_slice = row['name']

        # 임팩트 순으로 후보군 정렬
        self.pivot_candidates = sorted(self.pivot_candidates, key=lambda x: x['impact'], reverse=True)

        if worst_slice:
            self.output_callback(f"🚩 [Pivot Found] '{worst_slice}' (Impact Score: {max_impact:.1f})", True)
        return worst_slice

    def get_total_dur(self, tp):
        try:
            res = tp.query("SELECT (end_ts - start_ts)/1e6 as dur FROM trace_bounds").as_pandas_dataframe()
            return res.iloc[0, 0] if not res.empty and pd.notna(res.iloc[0, 0]) else 1.0
        except Exception: return 1.0


    def get_global_bounds(self, tp_type="slow"):
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        if tp is None: return None
        
        try:
            # trace_bounds는 min/max가 필요 없습니다. 
            # 이미 단 한 줄의 [start_ts, end_ts]가 들어있는 테이블이기 때문입니다.
            res = tp.query("SELECT start_ts, end_ts FROM trace_bounds").as_pandas_dataframe()
            
            if not res.empty and pd.notna(res.iloc[0, 0]):
                return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
                
            # [Fallback] 만약 trace_bounds가 비어있다면, slice 테이블에서 직접 추출
            res = tp.query("SELECT MIN(ts), MAX(ts+dur) FROM slice").as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
                
        except Exception as e:
            self.output_callback(f"⚠️ [Bounds Error] Failed to get global bounds: {str(e)}")
            
        return None

    def get_slice_bounds(self, tp_type, utid, name, scope_ts=None):
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        if tp is None: return None

        # 싱글 쿼트 대응 및 앞뒤 공백 제거
        clean_name = name.strip().replace("'", "''")
        
        # [개선] 단일 트랙이 아닌, 해당 utid와 관련된 모든 thread_track을 뒤짐
        # [개선] 정확히 일치(=)뿐만 아니라 유연한 매칭(LIKE) 옵션 고려 가능 (여기선 = 유지)
        query = f"""
            SELECT ts, (ts + dur) as end_ts 
            FROM slice 
            WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid}) 
            AND name = '{clean_name}'
        """
        
        if scope_ts:
            query += f" AND ts >= {scope_ts[0]} AND ts <= {scope_ts[1]}"
        
        # 지연 분석이므로 가장 긴 놈을 우선
        query += " ORDER BY dur DESC LIMIT 1"
        
        try:
            res = tp.query(query).as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
            
            # [보험] 만약 못 찾았다면, 이름 앞뒤에 공백이 있는지 LIKE로 한 번 더 시도
            query_retry = query.replace(f"name = '{clean_name}'", f"name LIKE '%{clean_name}%'")
            res = tp.query(query_retry).as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]

        except Exception as e:
            self.output_callback(f"⚠️ [Query Error] {str(e)}")
            
        return None

    def get_sync_bounds(self, tp_type, reference_ts):
        duration = reference_ts[1] - reference_ts[0]
        bounds = self.get_global_bounds(tp_type)
        return [bounds[0], bounds[0] + duration] if bounds else None

    def check_thread_scheduling(self, thread_name="auto"):
        return self._common_api.check_thread_scheduling(thread_name)

    def profile_thread_functions(self, thread_name="auto"):
        return self._common_api.profile_thread_functions(thread_name)