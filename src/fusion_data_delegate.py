import pandas as pd
import numpy as np
from common_api import CommonAPI

class FusionDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.utid_n = None
        self.utid_s = None
        self.target_package = None
        self.output_callback = output_callback
        self.num_cpus = 8  # 기본값, init에서 동적 업데이트

    def init(self, trace_normal, trace_slow, target_package):
        self.target_package = target_package
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
        def get_metrics(tp, utid, ts, label=""):
            # [방어 1] 타겟 좌표가 None인 경우 (가장 빈번한 에러 포인트)
            if ts is None or not isinstance(ts, (list, tuple)) or len(ts) < 2:
                return f"R?,Rn?,S?,D?|L:NoDataIn{label}|C:TargetNotFound"

            duration_ns = ts[1] - ts[0]
            # [방어 2] 시간 범위가 0이거나 역전된 경우
            if duration_ns <= 0:
                return f"R0,Rn0,S0,D0|L:None|C:InvalidTimeRange"

            # 1. CPU Scheduling States (R, Rn, S, D) 분석
            # num_cpus를 분모에 넣어 '점유율'로 환산 (티타늄과 다른 점)
            query_sched = f"""
                SELECT 
                    state, 
                    SUM(dur) * 100.0 / ({self.num_cpus} * {duration_ns}) as ratio
                FROM sched 
                WHERE utid = {utid} 
                AND ts >= {ts[0]} AND ts < {ts[1]}
                GROUP BY state
            """
            try:
                sched_df = tp.query(query_sched).as_pandas_dataframe()
                states = {'Running': 0, 'R': 0, 'S': 0, 'D': 0} # R은 Runnable(Rn)로 매핑되기도 함
                
                for _, row in sched_df.iterrows():
                    s = row['state']
                    val = round(row['ratio'], 1)
                    if s == 'Running': states['Running'] = val
                    elif s == 'R': states['R'] = val # Runnable (Rn)
                    elif s == 'S': states['S'] = val
                    elif s == 'D' or s == 'DK': states['D'] = val
            except Exception:
                states = {'Running': '?', 'R': '?', 'S': '?', 'D': '?'}

            # 2. 하위 슬라이스(Child Slices) Top 5 추출
            # 현재 범위 내에서 가장 점유율이 높은 함수들을 나열
            query_slice = f"""
                SELECT name, SUM(dur)/1e6 as sum_ms
                FROM slice 
                WHERE track_id = (SELECT id FROM thread_track WHERE utid = {utid} LIMIT 1)
                AND ts >= {ts[0]} AND ts < {ts[1]}
                GROUP BY 1 ORDER BY 2 DESC LIMIT 5
            """
            try:
                slice_df = tp.query(query_slice).as_pandas_dataframe()
                if not slice_df.empty:
                    # 슬라이스 이름 내 특수문자(#, $) 보존 및 리스트화
                    slice_list = [f"{row['name']}({row['sum_ms']:.1f}ms)" for _, row in slice_df.iterrows()]
                    l_str = ", ".join(slice_list)
                else:
                    l_str = "No_Child_Slices"
            except Exception:
                l_str = "Error_Fetching_Slices"

            # 3. 최종 메트릭 문자열 조립 (System Prompt 규격 준수)
            return f"R{states['Running']},Rn{states['R']},S{states['S']},D{states['D']}|L:[{l_str}]|C:OK"

        # Normal/Slow 각각의 지표 산출
        metrics_n = get_metrics(self._common_api.tp_n, utid_n, ts_n, label="Normal")
        metrics_s = get_metrics(self._common_api.tp_s, utid_s, ts_s, label="Slow")

        return f"### [FORENSIC DATA]\n- NORMAL: {metrics_n}\n- SLOW: {metrics_s}"

    def get_thread_candidates(self, tp, upid, global_ts=None):
        if tp is None or upid is None: return None
        ts_filter = f"AND ts >= {global_ts[0]} AND ts < {global_ts[1]}" if global_ts else ""

        query = f"""
            SELECT t.utid, t.name AS thread_name, (
                (CASE WHEN t.name = p.name THEN 150 ELSE 0 END) +
                (CASE WHEN EXISTS (
                    SELECT 1 FROM slice s JOIN thread_track tt ON s.track_id = tt.id
                    WHERE tt.utid = t.utid {ts_filter}
                    AND (s.name LIKE 'Choreographer%' OR s.name LIKE 'doFrame%') LIMIT 1
                ) THEN 250 ELSE 0 END) +
                COALESCE((SELECT SUM(dur)/1e6 FROM thread_state ts WHERE ts.utid = t.utid AND ts.state = 'R' {ts_filter}), 0) * 0.05
            ) AS total_score
            FROM thread t JOIN process p USING(upid)
            WHERE p.upid = {upid} ORDER BY total_score DESC;
        """
        df = tp.query(query).as_pandas_dataframe()
        return df if not df.empty else None
        
    def find_worst_slice(self, utid_n, utid_s):
        self.output_callback("🛰️ [Initial Scan] Searching for the most delayed pivot slice...", True)

        # [수정] trace_bounds 테이블 컬럼명 오류 해결 및 Fallback 로직 추가
        def get_total_dur(tp):
            try:
                # 1. 표준 trace_bounds 테이블 확인
                res = tp.query("SELECT (end_ts - start_ts)/1e6 as dur FROM trace_bounds").as_pandas_dataframe()
                if not res.empty and pd.notna(res.iloc[0, 0]):
                    return res.iloc[0, 0]
                
                # 2. 만약 trace_bounds가 비어있다면 slice 테이블에서 직접 계산 (Fallback)
                res = tp.query("SELECT (MAX(ts+dur) - MIN(ts))/1e6 as dur FROM slice").as_pandas_dataframe()
                return res.iloc[0, 0] if not res.empty else 1.0
            except Exception:
                return 1.0

        dur_n = get_total_dur(self._common_api.tp_n)
        dur_s = get_total_dur(self._common_api.tp_s)

        # 1. Slow 트레이스 상위 슬라이스 추출
        query_s = f"""
            SELECT name, SUM(dur)/1e6 as total_ms 
            FROM slice 
            WHERE track_id = (SELECT id FROM thread_track WHERE utid = {utid_s} LIMIT 1)
            AND dur > 0
            GROUP BY 1 ORDER BY 2 DESC LIMIT 15
        """
        df_s = self._common_api.tp_s.query(query_s).as_pandas_dataframe()
        if df_s.empty: return None

        worst_slice, max_ratio = None, 0

        for _, row in df_s.iterrows():
            # 싱글 쿼트(') 및 특수문자 대응
            safe_name = row['name'].replace("'", "''")
            slow_score = row['total_ms'] / dur_s
            
            # 2. Normal 대조 쿼리
            query_n = f"""
                SELECT SUM(dur)/1e6 as total_ms 
                FROM slice 
                WHERE track_id = (SELECT id FROM thread_track WHERE utid = {utid_n} LIMIT 1)
                AND name = '{safe_name}'
            """
            df_n = self._common_api.tp_n.query(query_n).as_pandas_dataframe()
            
            # SUM 결과가 NULL(데이터 없음)인 경우 처리
            n_ms_val = df_n.iloc[0]['total_ms'] if not df_n.empty else 0
            n_ms = n_ms_val if pd.notna(n_ms_val) and n_ms_val > 0 else 0.01
            
            normal_score = n_ms / dur_n
            ratio = slow_score / normal_score
            
            # [추가] 너무 짧은 슬라이스(노이즈)는 무시 (최소 2ms 이상인 것만)
            if row['total_ms'] > 2.0 and ratio > max_ratio:
                max_ratio = ratio
                worst_slice = row['name']

        if worst_slice:
            self.output_callback(f"🚩 [Pivot Found] '{worst_slice}' is {max_ratio:.1f}x heavier than normal.", True)
        
        return worst_slice

    def get_global_bounds(self, tp_type="slow"):
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        if tp is None: return None
        
        try:
            # [수정] trace_bounds는 min/max가 필요 없습니다. 
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