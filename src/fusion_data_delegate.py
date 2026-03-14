import pandas as pd
from src.common_api import CommonAPI

class FusionDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.utid_n = None
        self.utid_s = None
        self.target_package = None
        self.output_callback = output_callback

    def init(self, trace_normal, trace_slow, target_package):
        self.target_package = target_package
        self._common_api = CommonAPI(trace_normal, trace_slow, target_package)

    def identify_targets(self):
        # 1. 각 트레이스에서 후보군 추출
        res_n = self.get_thread_candidates(self._common_api.tp_n, self._common_api.upid_n)
        res_s = self.get_thread_candidates(self._common_api.tp_s, self._common_api.upid_s)
        
        # 2. 패키지명이 맞는데 데이터가 하나라도 없다면? -> 트레이스 수집 불량
        if res_n is None or res_s is None:
            missing = "NORMAL" if res_n is None else "SLOW"
            if res_n is None and res_s is None: missing = "BOTH"
            
            # ⚠️ 강한 에러 메시지: 패키지명이 맞다는 전제하에 '데이터의 부재'를 지적
            self.output_callback(f"🚨 [CRITICAL] 패키지 '{self.target_package}'의 데이터가 {missing} 트레이스에서 발견되지 않습니다.")
            self.output_callback(f"💡 트레이스 수집 시점에 앱이 실행 중이었는지, 혹은 버퍼 오버플로우가 발생했는지 확인하십시오.")
            return None, None, None

        # 3. 데이터가 있다면 가장 유력한(Score 1위) 스레드를 타겟으로 고정
        target_row_s = res_s.iloc[0]
        target_name = target_row_s['thread_name']
        
        # 이름 기반 매칭 시도
        match_n = res_n[res_n['thread_name'] == target_name]
        
        if not match_n.empty:
            utid_n = int(match_n.iloc[0]['utid'])
        else:
            # 이름이 완벽히 일치하지 않더라도 패키지가 맞으므로, Normal의 최우선 스레드와 강제 매칭
            utid_n = int(res_n.iloc[0]['utid'])
            self.output_callback(f"⚠️ [NOTICE] 동일 이름 스레드 부재. 유사 스레드(Score 1위)와 대조를 시작합니다.")

        self.utid_n = utid_n
        self.utid_s = int(target_row_s['utid'])
        self.target_thread = target_name
        
        return self.utid_n, self.utid_s, self.target_thread

    def generate_cfs(self, utid_n, ts_n, utid_s, ts_s):
        def get_metrics(tp, utid, ts):
            # 1. State Normalization: 'Runnable', 'R+', 'Running' 등을 표준화
            s_df = tp.query(f"""
                SELECT 
                    CASE 
                        WHEN state IN ('R', 'Running') THEN 'R'
                        WHEN state IN ('R+', 'Runnable') THEN 'Rn'
                        WHEN state IN ('S', 'Sleeping') THEN 'S'
                        ELSE state 
                    END as simple_state,
                    SUM(dur)/1e6 as ms 
                FROM thread_state 
                WHERE utid={utid} AND ts BETWEEN {ts[0]} AND {ts[1]} 
                GROUP BY 1
            """).as_pandas_dataframe()
            s_map = {row['simple_state']: int(row['ms']) for _, row in s_df.iterrows()}
            
            # 2. Slice Naming: 앞이 아닌 뒤를 잘라 클래스/메소드 식별력 강화
            l_df = tp.query(f"""
                SELECT name, SUM(dur)/1e6 as ms 
                FROM slice 
                WHERE track_id=(SELECT id FROM thread_track WHERE utid={utid}) 
                AND ts BETWEEN {ts[0]} AND {ts[1]} 
                AND parent_id IS NULL 
                ORDER BY ms DESC LIMIT 3
            """).as_pandas_dataframe()
            # 뒤쪽 12글자를 가져와 핵심 메소드명(e.g., ..doFrame) 보존
            l_str = ",".join([f"{row['name'][-12:]}({int(row['ms'])})" for _, row in l_df.iterrows()])
            
            # 3. CPU Load: 안정적인 나눗셈 및 NaN 처리
            duration_ns = ts[1] - ts[0]
            if duration_ns <= 0: return "R0,Rn0,S0|L:None|C:Load0%"
            
            c_df = tp.query(f"""
                SELECT (SUM(dur)*100.0 / ((SELECT MAX(cpu)+1 FROM sched) * {duration_ns})) as load 
                FROM sched 
                WHERE ts BETWEEN {ts[0]} AND {ts[1]}
            """).as_pandas_dataframe()
            load_val = int(c_df['load'].iloc[0]) if not c_df.empty and pd.notna(c_df['load'].iloc[0]) else 0

            if load_val > 0:
                load_final = f"Load{int(load_val)}%"
            else:
                # 동일 프로세스(upid) 내 모든 스레드의 R+Rn 합산
                p_load_df = tp.query(f"""
                    SELECT SUM(dur)*100.0 / {duration_ns} as proc_load
                    FROM thread_state
                    WHERE utid IN (SELECT utid FROM thread WHERE upid = (SELECT upid FROM thread WHERE utid={utid}))
                    AND state IN ('R', 'Running', 'R+', 'Runnable')
                    AND ts BETWEEN {ts[0]} AND {ts[1]}
                """).as_pandas_dataframe()
                p_load = p_load_df['proc_load'].iloc[0] if not p_load_df.empty and pd.notna(p_load_df['proc_load'].iloc[0]) else 0
                load_final = f"ProcLoad({p_load/100:.1f})" if p_load > 0 else "Unknown"
            
            return f"R{s_map.get('R',0)},Rn{s_map.get('Rn',0)},S{s_map.get('S',0)}|L:{l_str}|C:{load_final}"

        n_data = get_metrics(self._common_api.tp_n, utid_n, ts_n)
        s_data = get_metrics(self._common_api.tp_s, utid_s, ts_s)
        return f"[CONTRAST]\nNORMAL: {n_data}\nSLOW  : {s_data}"

    def get_thread_candidates(self, tp, upid):
        query = f"""
            SELECT 
                t.utid,
                t.name AS thread_name,
                ((CASE WHEN t.name = p.name THEN 100 ELSE 0 END) +
                (CASE WHEN EXISTS (
                    SELECT 1 FROM slice s 
                    JOIN thread_track tt ON s.track_id = tt.id
                    WHERE tt.utid = t.utid 
                    AND (s.name LIKE '%doFrame%' OR s.name LIKE '%Choreographer%')
                ) THEN 200 ELSE 0 END) +
                (COUNT(s.id) * 0.01)) AS total_score
            FROM thread t
            JOIN process p USING(upid)
            LEFT JOIN thread_track tt ON t.utid = tt.utid
            LEFT JOIN slice s ON tt.id = s.track_id
            WHERE p.upid = {upid}
            GROUP BY t.utid
            ORDER BY total_score DESC;
        """
        df = tp.query(query).as_pandas_dataframe()
        return df if not df.empty else None

    def get_global_bounds(self, tp_type="slow"):
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        if tp is None: return None
        res = tp.query("SELECT min(ts), max(ts) FROM trace_bounds").as_pandas_dataframe()
        if not res.empty and pd.notna(res.iloc[0, 0]):
            return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
        return None

    def get_slice_bounds(self, tp_type, utid, name):
        """AI가 요청한 슬라이스의 정확한 시간 범위를 찾습니다."""
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        query = f"""
            SELECT min(ts), max(ts) FROM slice 
            WHERE track_id=(SELECT id FROM thread_track WHERE utid={utid}) 
            AND name = '{name}'
        """
        res = tp.query(query).as_pandas_dataframe()
        if not res.empty and pd.notna(res.iloc[0, 0]):
            # 시간 뒤집힘 방지용 min/max 처리
            s, e = res.iloc[0, 0], res.iloc[0, 1]
            return [int(min(s, e)), int(max(s, e))]
        return None

    def get_sync_bounds(self, tp_type, reference_ts):
        """정상 트레이스의 분석 시작점을 지연 트레이스와 동기화합니다."""
        duration = reference_ts[1] - reference_ts[0]
        bounds_n = self.get_global_bounds("normal")
        if bounds_n:
            # 기본적으로 정상 트레이스의 시작부터 지연 트레이스 길이만큼 잡음
            return [bounds_n[0], bounds_n[0] + duration]
        return None

    def check_thread_scheduling(self, thread_name="auto"):
        return self._common_api.check_thread_scheduling(thread_name)

    def profile_thread_functions(self, thread_name="auto"):
        return self._common_api.profile_thread_functions(thread_name)