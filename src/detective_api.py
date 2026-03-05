from perfetto.trace_processor import TraceProcessor

class DetectiveAPI:
    def __init__(self, trace_path):
        self.tp = TraceProcessor(trace_path)
        self.min_ts = self.tp.query("SELECT min(ts) FROM slice").as_pandas_dataframe().iloc[0,0]
        pass

    # API 1: 전체 타임라인 지도
    def get_milestones(self):
        sql = """
            SELECT p.name as proc, s.name as slice,
                   (s.ts - (SELECT min(ts) FROM slice))/1e6 as start_offset_ms,
                   (s.dur/1e6) as dur_ms
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            JOIN process p ON t.upid = p.upid
            WHERE s.name IN ('bindApplication', 'installProviders', 'activityStart', 'activityResume', 'Choreographer#doFrame', 'reportFullyDrawn')
            ORDER BY s.ts ASC
        """
        return self.tp.query(sql).as_pandas_dataframe().to_markdown(index=False)

    # API 2: 메인 스레드 헤비 슬라이스
    def get_main_thread_heavy(self, target_process=None):
        where = f"WHERE t.name = 'main' AND p.name = '{target_process}'" if target_process else "WHERE t.name = 'main'"
        sql = f"""
            SELECT p.name as proc, s.name as slice, sum(s.dur)/1e6 as total_ms, count(*) as cnt
            FROM slice s JOIN thread_track tt ON s.track_id = tt.id JOIN thread t ON tt.utid = t.utid JOIN process p ON t.upid = p.upid
            {where} GROUP BY 1, 2 ORDER BY total_ms DESC LIMIT 15
        """
        return self.tp.query(sql).as_pandas_dataframe().to_markdown(index=False)

    # API 3: 바인더 지연 추적
    def get_binder_calls(self, target_process=None):
        where = f"WHERE s.name LIKE 'binder%' AND p.name = '{target_process}'" if target_process else "WHERE s.name LIKE 'binder%'"
        sql = f"""
            SELECT p.name as proc, s.name as slice, sum(s.dur)/1e6 as total_ms, count(*) as cnt
            FROM slice s JOIN thread_track tt ON s.track_id = tt.id JOIN thread t ON tt.utid = t.utid JOIN process p ON t.upid = p.upid
            {where} GROUP BY 1, 2 ORDER BY total_ms DESC LIMIT 10
        """
        return self.tp.query(sql).as_pandas_dataframe().to_markdown(index=False)

    # API 4: CPU 스케줄링 상태
    def get_cpu_states(self, target_process=None):
        where = f"WHERE t.name = 'main' AND p.name = '{target_process}'" if target_process else "WHERE t.name = 'main'"
        sql = f"""
            SELECT p.name as proc, ts.state, sum(ts.dur)/1e6 as total_ms
            FROM thread_state ts JOIN thread t ON ts.utid = t.utid JOIN process p ON t.upid = p.upid
            {where} GROUP BY 1, 2, 3 ORDER BY total_ms DESC
        """
        return self.tp.query(sql).as_pandas_dataframe().to_markdown(index=False)