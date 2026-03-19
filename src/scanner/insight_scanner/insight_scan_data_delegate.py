import pandas as pd
import numpy as np
from common_api import CommonAPI

class InsightScanDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.output_callback = output_callback
        self.package = None

    def init(self, trace_normal, trace_slow, target_package):
        # CommonAPI를 통해 타겟 패키지의 UPID 확보
        self._common_api = CommonAPI(trace_normal, trace_slow, target_package)
        self.package = target_package

    def fetch_deep_dive_package(self, window):
        # 분석 구간 및 50ms 마진 설정
        start_ns = window['start']
        end_ns = window['end']
        margin_ns = int(window.get('margin', 50.0) * 1e6)
        context_start_ns = start_ns - margin_ns
        
        upid = self._common_api.upid_s
        self.output_callback(f"🧬 [Data-Drilling] Extraction with Hard Caps (Optimized for DeepSeek-R1)...", True)

        # 각 API의 결과를 가져온 후, AI의 컨텍스트 보호를 위해 Hard Cap 적용
        return {
            # 1. v_stack: 상위 25개 (함수 호출 계층 및 주요 지연 파악용)
            "v_stack": self._get_vertical_stack(upid, start_ns, end_ns, context_start_ns)[:25],
            
            # 2. locks: 상위 10개 (가장 지배적인 병목 락 식별용)
            "locks": self._get_lock_contention(start_ns, end_ns, context_start_ns)[:10],
            
            # 3. neighbors: 상위 5개 (SQL에서 이미 LIMIT 5 적용됨)
            "neighbors": self._get_cpu_neighbors(start_ns, end_ns, context_start_ns),
            
            # 4. rhythm/binder: 전체 (데이터 양이 적어 전체 맥락 파악에 유리)
            "rhythm": self._get_state_transition_rhythm(upid, start_ns, end_ns, context_start_ns),
            "binder": self._get_binder_payload(upid, start_ns, end_ns, context_start_ns)
        }

    def _get_vertical_stack(self, upid, start_ns, end_ns, context_start_ns):
        query = f"""
            SELECT name, depth, 
                   SUM(MIN(ts + dur, {end_ns}) - MAX(ts, {start_ns})) / 1e6 as effective_ms
            FROM slice JOIN thread_track ON slice.track_id = thread_track.id
            JOIN thread USING (utid)
            WHERE upid = {upid} AND ts < {end_ns} AND (ts + dur) > {context_start_ns}
            GROUP BY 1, 2 HAVING effective_ms > 0.1 ORDER BY effective_ms DESC
        """
        return self._common_api.tp_s.query(query).as_pandas_dataframe().to_dict(orient='records')

    def _get_lock_contention(self, start_ns, end_ns, context_start_ns):
        query = f"""
            SELECT 
                s.name as lock_name, 
                t.name as thread_name,
                t.tid as tid,
                SUM(MIN(s.ts + s.dur, {end_ns}) - MAX(s.ts, {start_ns})) / 1e6 as wait_ms,
                SUBSTR(s.name, INSTR(s.name, 'object ') + 7) as lock_id
            FROM slice s 
            JOIN thread_track tt ON s.track_id = tt.id 
            JOIN thread t USING (utid)
            WHERE (s.name LIKE 'monitor contention%' OR s.name LIKE 'waiting on%')
            AND s.ts < {end_ns} AND (s.ts + s.dur) > {context_start_ns}
            GROUP BY 1, 2 ORDER BY wait_ms DESC
        """
        return self._common_api.tp_s.query(query).as_pandas_dataframe().to_dict(orient='records')

    def _get_cpu_neighbors(self, start_ns, end_ns, context_start_ns):
        query = f"""
            SELECT p.name as proc_name, 
                   SUM(MIN(sched.ts + sched.dur, {end_ns}) - MAX(sched.ts, {start_ns})) / 1e6 as cpu_ms
            FROM sched JOIN thread t USING (utid) JOIN process p USING (upid)
            WHERE sched.ts < {end_ns} AND (sched.ts + sched.dur) > {context_start_ns}
            AND p.name != '{self.package}'
            GROUP BY 1 ORDER BY cpu_ms DESC LIMIT 5
        """
        return self._common_api.tp_s.query(query).as_pandas_dataframe().to_dict(orient='records')

    def _get_state_transition_rhythm(self, upid, start_ns, end_ns, context_start_ns):
        query = f"""
            SELECT state, COUNT(*) as transitions,
                   SUM(MIN(ts + dur, {end_ns}) - MAX(ts, {start_ns})) / 1e6 as total_ms
            FROM thread_state JOIN thread USING (utid)
            WHERE upid = {upid} AND ts < {end_ns} AND (ts + dur) > {context_start_ns}
            GROUP BY 1
        """
        return self._common_api.tp_s.query(query).as_pandas_dataframe().to_dict(orient='records')

    def _get_binder_detailed_info(self, upid, start_ns, end_ns, context_start_ns):
        query = f"""
            SELECT 
                CASE 
                    WHEN s.name LIKE '%reply%' THEN 'Reply_Wait' 
                    WHEN s.name LIKE '%async%' THEN 'Async_Call'
                    ELSE 'Sync_Call' 
                END as binder_type,
                t.name as src_thread,
                COUNT(*) as count, 
                SUM(MIN(s.ts + s.dur, {end_ns}) - MAX(s.ts, {start_ns})) / 1e6 as total_ms
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t USING (utid)
            WHERE t.upid = {upid} 
            AND s.name LIKE 'binder%'
            AND s.ts < {end_ns} AND (s.ts + s.dur) > {context_start_ns}
            GROUP BY 1, 2
            ORDER BY total_ms DESC
        """
        return self._common_api.tp_s.query(query).as_pandas_dataframe().to_dict(orient='records')