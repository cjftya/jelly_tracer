import pandas as pd
import numpy as np
from src.common_api import CommonAPI

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
        self.output_callback("🔍 [Targeting] Identifying primary investigation targets...")

        res_n = self.get_thread_candidates(self._common_api.tp_n, self._common_api.upid_n)
        res_s = self.get_thread_candidates(self._common_api.tp_s, self._common_api.upid_s)

        if res_n is None or res_s is None:
            missing = "NORMAL" if res_n is None else "SLOW"
            if res_n is None and res_s is None: missing = "BOTH"
            self.output_callback(f"🚨 [CRITICAL] Package data not found in {missing} trace.")
            return None, None, None

        # Slow 트레이스에서 지연의 핵심 주범(1위) 선택
        target_row_s = res_s.iloc[0]
        self.target_thread = target_row_s['thread_name']
        self.utid_s = int(target_row_s['utid'])

        # Normal 트레이스에서 동일 이름 스레드 매칭
        match_n = res_n[res_n['thread_name'] == self.target_thread]

        if not match_n.empty:
            self.utid_n = int(match_n.iloc[0]['utid'])
            self.output_callback(f"🎯 [Target Locked] {self.target_thread} (Name Matched)")
        else:
            # Fallback: 이름 불일치 시 활동성 기반 강제 매칭
            target_row_n = res_n.iloc[0]
            self.utid_n = int(target_row_n['utid'])
            self.output_callback(f"⚠️ [NOTICE] Thread name mismatch. Matching by activity score.")
            self.output_callback(f"   - (N): {target_row_n['thread_name']} <-> (S): {self.target_thread}")
        
        return self.utid_n, self.utid_s, self.target_thread

    def generate_cfs(self, utid_n, ts_n, utid_s, ts_s, exclude_scopes=None):
        def get_metrics(tp, utid, ts):
            duration_ns = ts[1] - ts[0]
            if duration_ns <= 0: return "R0,Rn0,S0,D0|L:None|C:InvalidRange"

            # 1. Thread State 요약 (D 상태 분리 유지)
            s_df = tp.query(f"""
                SELECT 
                    CASE 
                        WHEN state IN ('R', 'Running') THEN 'R'
                        WHEN state IN ('R+', 'Runnable') THEN 'Rn'
                        WHEN state IN ('D', 'DK') THEN 'D'
                        WHEN state IN ('S', 'Sleeping') THEN 'S'
                        ELSE 'Other' 
                    END as simple_state,
                    SUM(dur)/1e6 as ms 
                FROM thread_state 
                WHERE utid={utid} AND ts >= {ts[0]} AND ts < {ts[1]} 
                GROUP BY 1
            """).as_pandas_dataframe()
            s_map = {row['simple_state']: int(row['ms']) for _, row in s_df.iterrows()}

            # 2. Slice 요약 (지능형 이름 단축 로직 적용)
            l_df = tp.query(f"""
                SELECT name, SUM(dur)/1e6 as ms 
                FROM slice 
                WHERE track_id=(SELECT id FROM thread_track WHERE utid={utid}) 
                AND ts >= {ts[0]} AND ts < {ts[1]}
                GROUP BY 1 ORDER BY ms DESC LIMIT 5
            """).as_pandas_dataframe()
            
            l_list = []
            for _, row in l_df.iterrows():
                raw_name = row['name']
                # [Smart Shortening Logic]
                if '#' in raw_name:
                    # '#'이 포함된 경우 (예: Choreographer#doFrame) 전체 보존
                    short_name = raw_name
                else:
                    # '.' 기준으로 잘라 최소 '클래스.메서드' 2단계는 유지 (예: MainActivity.onCreate)
                    parts = raw_name.split('.')
                    short_name = '.'.join(parts[-2:]) if len(parts) >= 2 else raw_name
                
                l_list.append(f"{short_name}({int(row['ms'])})")
                
            l_str = ",".join(l_list[:3]) or "NoSlice"

            # 3. CPU Stealer 식별 (JOIN 기반 고속 쿼리)
            stealer_df = tp.query(f"""
                SELECT t.name as s_name, SUM(s.dur)/1e6 as ms
                FROM sched s
                JOIN thread t ON s.utid = t.utid
                WHERE s.ts >= {ts[0]} AND s.ts < {ts[1]} 
                AND s.utid != {utid}
                GROUP BY 1 ORDER BY 2 DESC LIMIT 1
            """).as_pandas_dataframe()
            
            stealer_info = f"/{stealer_df.iloc[0]['s_name']}({int(stealer_df.iloc[0]['ms'])}ms)" if not stealer_df.empty else ""

            # 4. System Load 계산
            load_df = tp.query(f"""
                SELECT (SUM(dur)*100.0 / ({self.num_cpus} * {duration_ns})) as load 
                FROM sched WHERE ts >= {ts[0]} AND ts < {ts[1]}
            """).as_pandas_dataframe()
            
            load_val = int(load_df['load'].iloc[0]) if not load_df.empty and pd.notna(load_df['load'].iloc[0]) else 0
            load_final = f"Load{load_val}%" if load_val > 10 else "Idle"

            return f"R{s_map.get('R',0)},Rn{s_map.get('Rn',0)},S{s_map.get('S',0)},D{s_map.get('D',0)}|L:{l_str}|C:{load_final}{stealer_info}"

        n_data = get_metrics(self._common_api.tp_n, utid_n, ts_n)
        s_data = get_metrics(self._common_api.tp_s, utid_s, ts_s)
        return f"[CONTRAST]\nNORMAL: {n_data}\nSLOW  : {s_data}"

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

    def get_global_bounds(self, tp_type="slow"):
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        if tp is None: return None
        res = tp.query("SELECT min(ts), max(ts) FROM trace_bounds").as_pandas_dataframe()
        return [int(res.iloc[0, 0]), int(res.iloc[0, 1])] if not res.empty and pd.notna(res.iloc[0, 0]) else None

    def get_slice_bounds(self, tp_type, utid, name, scope_ts=None):
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        if tp is None: return None

        # [포인트 1] 정확한 이름 매칭 (AI가 보존한 #, $, : 등의 기호가 포함된 원본 이름 사용)
        # [포인트 2] thread_track 조회를 통해 타겟 스레드 내의 슬라이스만 선별
        query = f"""
            SELECT ts, (ts + dur) as end_ts 
            FROM slice 
            WHERE track_id = (SELECT id FROM thread_track WHERE utid = {utid} LIMIT 1) 
            AND name = '{name}'
        """
        
        # [포인트 3] 상위 스코프(부모 슬라이스) 정보가 있다면, 해당 시간 범위 내에서만 탐색하여 
        # 분석의 정밀도를 'Depth-First' 방식으로 강화 (수사 범위 압축)
        if scope_ts:
            query += f" AND ts >= {scope_ts[0]} AND ts <= {scope_ts[1]}"
        
        # [포인트 4] 동일한 이름의 슬라이스가 여러 개일 경우, 지연의 주범일 가능성이 높은 
        # '가장 긴(dur DESC)' 슬라이스를 분석 우선순위로 선정
        query += " ORDER BY dur DESC LIMIT 1"
        
        try:
            res = tp.query(query).as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                start_ts = int(res.iloc[0, 0])
                end_ts = int(res.iloc[0, 1])
                return [start_ts, end_ts]
                
        except Exception as e:
            self.output_callback(f"⚠️ [Data Error] Failed to fetch bounds for '{name}': {str(e)}")
            
        return None

    def get_sync_bounds(self, tp_type, reference_ts):
        duration = reference_ts[1] - reference_ts[0]
        bounds = self.get_global_bounds(tp_type)
        return [bounds[0], bounds[0] + duration] if bounds else None

    def check_thread_scheduling(self, thread_name="auto"):
        return self._common_api.check_thread_scheduling(thread_name)

    def profile_thread_functions(self, thread_name="auto"):
        return self._common_api.profile_thread_functions(thread_name)