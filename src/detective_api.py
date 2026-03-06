from perfetto.trace_processor import TraceProcessor


class DetectiveAPI:
    def __init__(self, normal_trace_path, slow_trace_path, package_name):
        self.tp_n = TraceProcessor(file_path=normal_trace_path)
        self.tp_s = TraceProcessor(file_path=slow_trace_path)
        self.package = package_name
        # 수사 시작 전, 대상 앱의 고유 ID(uPid)부터 확보 (가장 중요)
        self.upid_n = self._get_upid(self.tp_n)
        self.upid_s = self._get_upid(self.tp_s)

        if self.upid_n is None or self.upid_s is None:
            print(
                "⚠️ 경고: 트레이스 내에서 지정된 패키지를 찾을 수 없습니다. 'initial_system_scan'으로 프로세스 명단을 먼저 확인하세요."
            )

    def _get_upid(self, tp):
        query = f"SELECT upid FROM process WHERE name = '{self.package}' LIMIT 1"
        res = tp.query(query).as_pandas_dataframe()
        return res["upid"].iloc[0] if not res.empty else None

    def _run_dual_query(self, sql):
        """Normal과 Slow 트레이스에서 동일 쿼리를 실행하고 결과를 반환"""
        df_n = self.tp_n.query(sql).as_pandas_dataframe()
        df_s = self.tp_s.query(sql).as_pandas_dataframe()
        return {
            "normal": df_n.to_dict(orient="records") if not df_n.empty else [],
            "slow": df_s.to_dict(orient="records") if not df_s.empty else [],
        }

    def initial_system_scan(self, keyword):
        print(f"🔎 전체 시스템 스캔 및 '{keyword}' 관련성 분석...")

        # 1. 마일스톤 SQL: 시스템 전체의 주요 성능 앵커 포인트 추출
        milestone_sql = """
        SELECT 
            name, 
            COUNT(*) as call_count,
            CAST(AVG(dur) / 1e6 AS FLOAT) as avg_ms,
            CAST(SUM(dur) / 1e6 AS FLOAT) as total_dur_ms
        FROM slice
        WHERE name IN ('bindApplication', 'activityStart', 'Choreographer#doFrame', 'reportFullyDrawn', 'PostFork')
        GROUP BY name
        """

        # 2. 시스템 와이드 프로세스 스캔 SQL: 누가 CPU를 가장 많이 쓰고 있는가?
        # 특정 패키지로 필터링하지 않고, 전체 시스템에서 가장 '바쁜' 놈들 Top 15를 추출합니다.
        process_sql = """
        SELECT 
            p.name as process_name, 
            p.upid, 
            p.pid,
            SUM(s.dur) / 1e6 as cpu_time_ms
        FROM process p
        JOIN thread t ON p.upid = t.upid
        JOIN sched s ON t.utid = s.utid
        GROUP BY p.upid
        ORDER BY cpu_time_ms DESC
        LIMIT 15
        """

        # 데이터 추출 (Normal / Slow 대조)
        milestones_n = self.tp_n.query(milestone_sql).as_pandas_dataframe()
        milestones_s = self.tp_s.query(milestone_sql).as_pandas_dataframe()

        processes_n = self.tp_n.query(process_sql).as_pandas_dataframe()
        processes_s = self.tp_s.query(process_sql).as_pandas_dataframe()

        # 3. 데이터 결합 및 AI용 리포트 작성
        report = {
            "milestone_delta": [],
            "system_top_processes": {
                "normal": processes_n.to_dict(orient="records"),
                "slow": processes_s.to_dict(orient="records"),
            },
            "investigation_target_hint": keyword,  # AI가 명단에서 우리 앱을 찾을 수 있게 힌트 제공
        }

        # 마일스톤 Delta 분석 (어디서 지연이 시작되었는가?)
        all_events = set(milestones_n["name"]).union(set(milestones_s["name"]))
        for event in all_events:
            m_n = milestones_n[milestones_n["name"] == event]
            m_s = milestones_s[milestones_s["name"] == event]

            val_n = m_n["total_dur_ms"].values[0] if not m_n.empty else 0
            val_s = m_s["total_dur_ms"].values[0] if not m_s.empty else 0
            delta = val_s - val_n

            report["milestone_delta"].append(
                {
                    "event": event,
                    "normal_ms": round(val_n, 2),
                    "slow_ms": round(val_s, 2),
                    "delta_ms": round(delta, 2),
                    "status": "⚠️ REGRESSION" if delta > 50 else "OK",
                }
            )

        return report

    # 2번 API: Self-Duration 기반 분석
    def profile_main_thread(self, top_n=15):
        if not self.upid_s:
            return {"error": "Target upid missing"}
        sql = f"""
        SELECT s.name, COUNT(*) as count, SUM(s.dur)/1e6 as total_ms
        FROM slice s JOIN thread_track t ON s.track_id = t.id
        WHERE t.upid = {self.upid_s} AND t.name = '{self.package}'
        GROUP BY s.name ORDER BY total_ms DESC LIMIT {top_n}
        """
        return self._run_dual_query(sql)

    # 3번 API: Binder 상대방 확인
    def trace_binder_calls(self, min_dur_ms=5):
        if not self.upid_s:
            return {"error": "Target upid missing"}
        sql = f"""
        SELECT s.name, s.dur/1e6 as dur_ms, 
               (SELECT p.name FROM process p WHERE p.upid = b.dest_upid) as destination
        FROM slice s JOIN binder_transaction b ON s.id = b.slice_id
        WHERE s.upid = {self.upid_s} AND s.dur > {min_dur_ms * 1e6}
        ORDER BY dur_ms DESC LIMIT 20
        """
        return self._run_dual_query(sql)

    # 4. 스레드 상태 분석 (Running, Runnable, Sleep)
    def check_thread_states(self, thread_type="main"):
        upid = self.upid_s
        if not upid:
            return {"error": "Target upid missing"}

        thread_filter = (
            f"AND t.name = '{self.package}'" if thread_type == "main" else ""
        )
        sql = f"""
        SELECT state, SUM(dur)/1e6 as total_dur_ms 
        FROM thread_state ts JOIN thread t USING (utid)
        WHERE t.upid = {upid} {thread_filter}
        GROUP BY state
        """
        return self._run_dual_query(sql)

    # 5. Lock 경합 분석
    def check_lock_contention(self):
        if not self.upid_s:
            return {"error": "Target upid missing"}
        sql = f"""
        SELECT name, dur/1e6 as dur_ms FROM slice s
        JOIN thread_track t ON s.track_id = t.id
        WHERE t.upid = {self.upid_s} AND name LIKE 'Lock contention%'
        ORDER BY dur DESC LIMIT 20
        """
        return self._run_dual_query(sql)

    # 6. GC 및 메모리 분석
    def analyze_memory_gc(self):
        if not self.upid_s:
            return {"error": "Target upid missing"}
        sql = f"""
        SELECT name, dur/1e6 as dur_ms FROM slice s
        JOIN thread_track t ON s.track_id = t.id
        WHERE t.upid = {self.upid_s} AND (name LIKE '%GC%' OR name LIKE '%Heap%')
        ORDER BY dur DESC LIMIT 20
        """
        return self._run_dual_query(sql)

    # 7. 자유 SQL 수사
    def execute_custom_sql(self, query, reason):
        print(f"🕵️ AI 수사관의 특수 요청: {reason}")
        return self._run_dual_query(query)
