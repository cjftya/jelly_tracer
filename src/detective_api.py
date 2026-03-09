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
        # 1단계: [신규] 패키지 리스트 지도로 UID부터 확보 (가장 정확)
        try:
            pkg_query = f"SELECT uid FROM package_list WHERE package_name = '{self.package}' LIMIT 1"
            pkg_res = tp.query(pkg_query).as_pandas_dataframe()
            if not pkg_res.empty:
                uid = pkg_res["uid"].iloc[0]
                # 확보한 UID로 실행된 프로세스 중 가장 핵심(보통 upid가 가장 큼)인 것 추출
                upid_query = f"SELECT upid FROM process WHERE uid = {uid} ORDER BY upid DESC LIMIT 1"
                res = tp.query(upid_query).as_pandas_dataframe()
                if not res.empty:
                    print(
                        f"ℹ️ 알림: package_list(UID:{uid})를 통해 upid를 검거했습니다."
                    )
                    return int(res["upid"].iloc[0])
        except:
            pass  # package_list 테이블이 없는 트레이스일 경우 통과

        # 2단계: 프로세스 테이블 검색 (검색어 유연화)
        short_name = self.package.split(".")[-1]  # 'gallery3d' 추출
        query_process = f"""
            SELECT upid FROM process 
            WHERE (name = '{self.package}' OR name LIKE '%{short_name}%')
            AND upid IS NOT NULL 
            LIMIT 1
        """
        res = tp.query(query_process).as_pandas_dataframe()
        if not res.empty:
            return int(res["upid"].iloc[0])

        # 3단계: 스레드 테이블 역추적
        query_thread = f"""
            SELECT upid FROM thread 
            WHERE (name = '{self.package}' OR name LIKE '%{short_name}%')
            AND upid IS NOT NULL 
            LIMIT 1
        """
        res = tp.query(query_thread).as_pandas_dataframe()
        if not res.empty:
            print(f"ℹ️ 알림: thread 테이블을 통해 upid를 찾았습니다.")
            return int(res["upid"].iloc[0])

        return None

    def _run_dual_query(self, sql_template):
        # 💡 안전장치: upid가 없으면 쿼리를 실행하지 않고 빈 결과를 반환
        if self.upid_n is None or self.upid_s is None:
            print(
                f"⚠️ 경고: '{self.package}'의 ID를 찾지 못해 쿼리를 스킵합니다. (N:{self.upid_n}, S:{self.upid_s})"
            )
            return {"normal": [], "slow": [], "error": "Package not found in trace"}

        # 1. Normal용 uPid 주입 및 실행
        # 만약 sql_template에 {upid}가 없더라도 replace는 에러 없이 작동합니다.
        sql_n = sql_template.replace("{upid}", str(self.upid_n))
        df_n = self.tp_n.query(sql_n).as_pandas_dataframe()

        # 2. Slow용 uPid 주입 및 실행
        sql_s = sql_template.replace("{upid}", str(self.upid_s))
        df_s = self.tp_s.query(sql_s).as_pandas_dataframe()

        df_n = df_n.round(2)
        df_s = df_s.round(2)

        # 3. 데이터 다이어트 (토큰 폭발 방지: 불필요한 ID 컬럼 제거)
        # AI 분석에 필요 없는 upid, utid 등은 여기서 제거하면 토큰을 아낄 수 있습니다.
        cols_to_drop = ["upid", "utid", "track_id"]
        df_n = df_n.drop(columns=[c for c in cols_to_drop if c in df_n.columns])
        df_s = df_s.drop(columns=[c for c in cols_to_drop if c in df_s.columns])

        # 4. 기존 형식 그대로 반환
        return {
            "normal": df_n.to_dict(orient="records") if not df_n.empty else [],
            "slow": df_s.to_dict(orient="records") if not df_s.empty else [],
        }

    def initial_system_scan(self, keyword):
        print(f"🔎 시스템 광역 스캔 및 델타 정밀 분석 (Target: {keyword})...")

        # 1. 마일스톤 SQL: 더 다양한 구간 추가 (Choreographer, 지연 지점 확인용)
        milestone_sql = """
        SELECT name, CAST(SUM(dur) / 1e6 AS FLOAT) as total_dur_ms
        FROM slice
        WHERE name IN ('bindApplication', 'activityStart', 'Choreographer#doFrame', 
                    'reportFullyDrawn', 'PostFork', 'viewVisibility')
        GROUP BY name
        """

        # 2. 스레드 레벨 CPU 점유율 SQL: 이름 복구 및 스레드 단위 정밀화
        # p.name(프로세스)과 t.name(스레드)을 같이 가져와서 명확히 구분합니다.
        thread_cpu_sql = """
        SELECT 
            COALESCE(p.name, t.name, '[Unknown]') as proc_name,
            t.name as thread_name,
            p.pid,
            SUM(s.dur) / 1e6 as cpu_ms
        FROM sched s
        JOIN thread t USING (utid)
        LEFT JOIN process p USING (upid)
        GROUP BY t.utid
        ORDER BY cpu_ms DESC
        LIMIT 30
        """

        # 데이터 추출
        m_n = self.tp_n.query(milestone_sql).as_pandas_dataframe()
        m_s = self.tp_s.query(milestone_sql).as_pandas_dataframe()
        t_n = self.tp_n.query(thread_cpu_sql).as_pandas_dataframe()
        t_s = self.tp_s.query(thread_cpu_sql).as_pandas_dataframe()

        # 3. CPU 델타 계산 (누가 이전보다 더 많이 일했는가?)
        cpu_deltas = []
        # 지연(Slow) 버전의 스레드들을 기준으로 비교
        for _, row_s in t_s.iterrows():
            # 동일한 프로세스/스레드 이름을 가진 녀석을 정상 버전에서 찾음
            row_n = t_n[
                (t_n["proc_name"] == row_s["proc_name"])
                & (t_n["thread_name"] == row_s["thread_name"])
            ]

            if row_n.empty:
                # 🚨 [신규 용의자 발견] Normal에는 아예 없던 녀석
                cpu_n = 0
                status = "🆕 NEW ACTOR"
            else:
                cpu_n = row_n["cpu_ms"].values[0]
                status = "🔴 INCREASED" if (row_s["cpu_ms"] - cpu_n) > 10 else "STABLE"

            delta = row_s["cpu_ms"] - cpu_n

            if abs(delta) > 3 or keyword in row_s["proc_name"]:
                cpu_deltas.append(
                    {
                        "process": row_s["proc_name"],
                        "thread": row_s["thread_name"],
                        "delta_ms": round(delta, 2),
                        "status": status,  # 신규인지 기존인지 명시
                        "current_total_ms": round(row_s["cpu_ms"], 2),
                    }
                )

        report = {
            "milestone_analysis": [],
            "cpu_thieves_top_10": sorted(
                cpu_deltas, key=lambda x: x["delta_ms"], reverse=True
            )[:10],
            "target_app_keyword": keyword,
        }

        # 마일스톤 분석 (기존 로직 유지하되 가독성 향상)
        all_events = set(m_n["name"]).union(set(m_s["name"]))
        for event in all_events:
            v_n = (
                m_n[m_n["name"] == event]["total_dur_ms"].sum() if not m_n.empty else 0
            )
            v_s = (
                m_s[m_s["name"] == event]["total_dur_ms"].sum() if not m_s.empty else 0
            )
            delta = v_s - v_n
            report["milestone_analysis"].append(
                {
                    "event": event,
                    "delta": round(delta, 2),
                    "verdict": "🚨 REGRESSION" if delta > 20 else "OK",
                }
            )

        return report

    def profile_main_thread(self, top_n=15):
        # 💡 핵심 로직: 이름으로 필터링하는 대신,
        # 해당 upid 안에서 slice(함수 호출) 기록이 가장 많은 스레드를 자동으로 찾아냅니다.
        sql = f"""
        WITH target_thread AS (
            SELECT tt.utid
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            WHERE t.upid = {{upid}}
            GROUP BY tt.utid
            ORDER BY SUM(s.dur) DESC
            LIMIT 1
        )
        SELECT 
            s.name as function_name,
            SUM(s.dur) / 1e6 as total_dur_ms,
            COUNT(*) as call_count,
            t.name as thread_real_name
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        WHERE t.upid = {{upid}}
          AND t.utid IN (SELECT utid FROM target_thread)
          AND s.dur > 0
        GROUP BY s.name, t.name
        ORDER BY total_dur_ms DESC
        LIMIT {top_n}
        """
        return self._run_dual_query(sql)

    def trace_binder_calls(self, min_dur_ms=2):
        print(f"🕵️‍♂️ {self.package} 외부 통신(Binder) 상태 확인 중...")

        # 1. 먼저 binder_transaction 테이블이 존재하는지 확인합니다.
        check_table_sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='binder_transaction'"

        # tp_n 기준 하나만 체크 (보통 한쪽 없으면 양쪽 다 없음)
        table_exists = not self.tp_n.query(check_table_sql).as_pandas_dataframe().empty

        if table_exists:
            # ✅ 정석적인 Binder 테이블 수사
            sql = f"""
            SELECT 
                t.name as caller_thread,
                s.name as call_name,
                s.dur / 1e6 as dur_ms,
                (SELECT p.name FROM process p JOIN binder_transaction bt ON p.upid = bt.dest_upid WHERE bt.slice_id = s.id LIMIT 1) as destination_process
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            JOIN binder_transaction b ON s.id = b.slice_id
            WHERE t.upid = {{upid}} AND s.dur > {min_dur_ms * 1e6}
            ORDER BY s.dur DESC LIMIT 20
            """
        else:
            # 🔍 [플랜 B] 테이블이 없을 때: slice 이름에서 binder 검색 (차선책)
            print(
                "ℹ️ 안내: 상세 binder_transaction 테이블이 없어 slice 기록에서 추정합니다."
            )
            sql = f"""
            SELECT 
                t.name as caller_thread,
                s.name as call_name,
                s.dur / 1e6 as dur_ms,
                'Unknown (No Binder Data)' as destination_process
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            WHERE t.upid = {{upid}} 
              AND (s.name LIKE 'binder%' OR s.name LIKE '%transaction%')
              AND s.dur > {min_dur_ms * 1e6}
            ORDER BY s.dur DESC LIMIT 20
            """

        return self._run_dual_query(sql)

    def check_thread_states(self, thread_type="auto"):
        print(f"🕵️‍♂️ {self.package} 스레드 스케줄링 상태 수사 중 ({thread_type})...")

        # 💡 핵심 수정: thread_track(tt)에는 upid가 없으므로 thread(t_sub)와 조인해야 합니다.
        target_filter = ""
        if thread_type == "auto":
            target_filter = """
            AND t.utid IN (
                SELECT tt.utid 
                FROM slice s 
                JOIN thread_track tt ON s.track_id = tt.id 
                JOIN thread t_sub ON tt.utid = t_sub.utid 
                WHERE t_sub.upid = {upid} 
                GROUP BY tt.utid 
                ORDER BY SUM(s.dur) DESC 
                LIMIT 1
            )
            """

        sql = f"""
        SELECT 
            t.name as thread_name,
            ts.state, 
            SUM(ts.dur)/1e6 as total_dur_ms
        FROM thread_state ts 
        JOIN thread t USING (utid)
        WHERE t.upid = {{upid}}
          {target_filter}
        GROUP BY t.name, ts.state
        ORDER BY total_dur_ms DESC
        """
        return self._run_dual_query(sql)

    def check_lock_contention(self):
        print(f"🕵️‍♂️ {self.package} 내부 스레드 자원 경합(Lock) 조사 중...")

        # 💡 개선 포인트:
        # 1. thread_track(tt) -> thread(t) 조인 추가로 upid 참조 오류 해결
        # 2. 'monitor contention'(Java)과 'Lock contention'(Native) 모두 포착
        # 3. 어떤 스레드가 고통받고 있는지 thread_name을 포함하여 리포트

        sql = f"""
        SELECT 
            t.name as thread_name,
            s.name as lock_details,
            s.dur / 1e6 as dur_ms
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        WHERE t.upid = {{upid}}
          AND (s.name LIKE 'Lock contention%' OR s.name LIKE 'monitor contention%')
          AND s.dur > 0
        ORDER BY s.dur DESC 
        LIMIT 20
        """
        return self._run_dual_query(sql)

    # 6. GC 및 메모리 분석
    def analyze_memory_gc(self):
        print(f"🕵️‍♂️ {self.package} 메모리 관리 및 GC(Garbage Collection) 수색 중...")

        # 💡 개선 포인트:
        # 1. thread_track -> thread 조인 추가로 upid 참조 오류 해결
        # 2. {upid} 템플릿 적용으로 Normal/Slow 델타 비교 가능
        # 3. GC뿐만 아니라 대량 할당(Alloc) 및 Heap 관리 함수까지 검색 범위 확대

        sql = f"""
        SELECT 
            t.name as thread_name,
            s.name as gc_event,
            s.dur / 1e6 as dur_ms
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        WHERE t.upid = {{upid}}
          AND (
              s.name LIKE '%GC%' 
              OR s.name LIKE '%GarbageCollection%' 
              OR s.name LIKE '%Alloc%' 
              OR s.name LIKE '%Heap%'
              OR s.name LIKE '%Free%'
          )
          AND s.dur > 0
        ORDER BY s.dur DESC 
        LIMIT 20
        """
        return self._run_dual_query(sql)

    # 7. 자유 SQL 쿼리
    def execute_custom_sql(self, query, reason):
        print(f"🕵️ AI의 특수 요청: {reason}")

        # 💡 개선 포인트:
        # AI가 {upid}를 잊어버리고 748 같은 숫자를 직접 넣지 않도록
        # 시스템 프롬프트에서 강조해야 하지만, 코드 단에서도 깔끔하게 전달합니다.

        try:
            return self._run_dual_query(query)
        except Exception as e:
            return {"error": f"SQL 수사 중 오류 발생: {str(e)}", "query": query}

    # 8번 API: 특정 스레드 내부 함수(Slice) 정밀 분석
    def profile_thread_functions(self, thread_name="auto"):
        """
        특정 스레드(예: 'Finish Thread', 'RenderThread')의 함수 실행 시간을 분석합니다.
        thread_name이 "auto"일 경우, 해당 프로세스에서 가장 일을 많이 한 스레드를 자동으로 잡습니다.
        """
        print(f"🕵️‍♂️ {self.package} 스레드({thread_name}) 내부 함수 전수 조사 중...")

        # 💡 개선 포인트:
        # 1. Join 경로 수정: slice -> thread_track -> thread (정석 경로)
        # 2. auto 모드: 이름을 모를 땐 가장 바쁜 놈을 추적하는 로직 삽입
        # 3. 중복 제거: _run_dual_query를 호출하여 중복 코드 제거

        target_thread_filter = ""
        if thread_name == "auto":
            target_thread_filter = """
            AND t.utid IN (
                SELECT tt.utid FROM slice s 
                JOIN thread_track tt ON s.track_id = tt.id 
                JOIN thread t_sub ON tt.utid = t_sub.utid
                WHERE t_sub.upid = {upid} 
                GROUP BY tt.utid ORDER BY SUM(s.dur) DESC LIMIT 1
            )
            """
        else:
            target_thread_filter = (
                f"AND (t.name = '{thread_name}' OR t.name LIKE '%{thread_name}%')"
            )

        sql = f"""
            SELECT 
                s.name as function_name, 
                SUM(s.dur)/1e6 as total_ms,
                COUNT(*) as call_count
            FROM slice s 
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            WHERE t.upid = {{upid}} 
              {target_thread_filter}
              AND s.dur > 0
            GROUP BY s.name 
            ORDER BY total_ms DESC 
            LIMIT 15
        """
        return self._run_dual_query(sql)
