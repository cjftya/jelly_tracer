import pandas as pd
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

        self.top_threads = (
            []
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

    def initial_system_scan(self, keyword):
        print(f"🔎 시스템 광역 스캔 및 델타 분석 시작 (Target: {keyword})")

        # 1. SQL 정의 (지휘관님의 기존 쿼리 유지, 데이터는 넉넉히 50개까지 수집)
        milestone_sql = """
        SELECT name, CAST(SUM(dur) / 1e6 AS FLOAT) as total_dur_ms
        FROM slice
        WHERE name IN ('bindApplication', 'activityStart', 'Choreographer#doFrame', 
                    'reportFullyDrawn', 'PostFork', 'viewVisibility')
        GROUP BY name
        """

        thread_cpu_sql = """
        SELECT 
            COALESCE(p.name, t.name, '[Unknown]') as proc_name,
            t.name as thread_name,
            SUM(s.dur) / 1e6 as cpu_ms
        FROM sched s
        JOIN thread t USING (utid)
        LEFT JOIN process p USING (upid)
        GROUP BY t.utid
        ORDER BY cpu_ms DESC
        LIMIT 50
        """

        # 데이터 추출
        m_n = self.tp_n.query(milestone_sql).as_pandas_dataframe()
        m_s = self.tp_s.query(milestone_sql).as_pandas_dataframe()
        t_n = self.tp_n.query(thread_cpu_sql).as_pandas_dataframe()
        t_s = self.tp_s.query(thread_cpu_sql).as_pandas_dataframe()

        # 2. 마일스톤 분석 (수량 적으므로 전수 대조)
        all_events = set(m_n["name"]).union(set(m_s["name"]))
        milestone_md = "### 🚩 Milestone Delta (Key Stages)\n| Event | Delta | Status |\n| :--- | :--- | :--- |\n"
        for event in sorted(all_events):
            v_n = (
                m_n[m_n["name"] == event]["total_dur_ms"].sum() if not m_n.empty else 0
            )
            v_s = (
                m_s[m_s["name"] == event]["total_dur_ms"].sum() if not m_s.empty else 0
            )
            delta = v_s - v_n
            verdict = "🚨 REGRESSION" if delta > 20 else "✅ OK"
            milestone_md += f"| {event} | {delta:+.2f}ms | {verdict} |\n"

        # [3. CPU Thread Delta 분석 및 Ratio 로직 개선]
        cpu_deltas = []
        for _, row_s in t_s.iterrows():
            row_n = t_n[
                (t_n["proc_name"] == row_s["proc_name"])
                & (t_n["thread_name"] == row_s["thread_name"])
            ]
            cpu_n = row_n["cpu_ms"].values[0] if not row_n.empty else 0
            delta = row_s["cpu_ms"] - cpu_n

            # 0.1ms 이상의 변화만 수집하여 노이즈 제거
            if abs(delta) > 0.1 or keyword in row_s["proc_name"]:
                cpu_deltas.append(
                    {
                        "name": f"{row_s['proc_name']} ({row_s['thread_name']})",
                        "delta": delta,
                        "is_new": row_n.empty,
                    }
                )

        # Delta 순 정렬
        cpu_deltas.sort(key=lambda x: x["delta"], reverse=True)

        # 🚀 [핵심: 양수 델타 기반 Ratio 계산]
        # 전체 '증가분'의 합계만 계산합니다. (지연의 원인을 찾기 위함)
        total_increase = sum(d["delta"] for d in cpu_deltas if d["delta"] > 0)

        # 만약 모든 델타가 0이거나 음수라면(성능 개선 상황), 절대값 합계를 분모로 사용
        denominator = (
            total_increase
            if total_increase > 0
            else sum(abs(d["delta"]) for d in cpu_deltas)
        )

        # [Registry] 상위 5위 스레드 이름 수첩에 기록
        self.top_threads = [d["name"].split(" (")[1][:-1] for d in cpu_deltas[:5]]

        # [4. 결과 마크다운 생성]
        top_5 = cpu_deltas[:5]
        others = cpu_deltas[5:]
        others_delta = sum(d["delta"] for d in others)

        thread_md = (
            f"\n### 🧵 Thread CPU Delta (Total Increase: +{total_increase:.2f}ms)\n"
        )
        thread_md += "| Rank | Thread (Process) | Delta | Ratio | Status |\n"
        thread_md += "| :--- | :--- | :--- | :--- | :--- |\n"

        # [수정본] 상태 판별 및 마크다운 행 생성 섹션
        for i, d in enumerate(top_5, 1):
            # 1. 지연 지분(Ratio) 계산 (양수일 때만)
            ratio = (
                (d["delta"] / denominator * 100)
                if denominator > 0 and d["delta"] > 0
                else 0
            )

            # 2. ⚪ STABLE 판별 로직 강화 (±0.1ms 기준)
            if d["delta"] > 0.1:
                status = "🔴 INC"
            elif d["delta"] < -0.1:
                status = "🟢 DEC"
            else:
                status = "⚪ STABLE"

            # 3. 마크다운 행 추가
            thread_md += f"| {i} | {d['name']} | {d['delta']:+.2f}ms | {ratio:.1f}% | {status} |\n"

        if others:
            # 기타 항목의 비중 합산 (역시 양수일 때만 의미 있음)
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            thread_md += f"| **기타** | **나머지 {len(others)}개 스레드 합계** | **{others_delta:+.2f}ms** | {others_ratio:.1f}% | - |\n"

        # 만약 total_increase가 0이면 AI에게 데이터가 동일함을 알리는 힌트 추가
        if total_increase <= 0:
            thread_md += "\n> 💡 **수사관 참고:** 유의미한 CPU 증가가 탐지되지 않았습니다. Cold Case Protocol 검토가 필요합니다."

        return milestone_md + thread_md

    def check_process_cpu(self):
        print("🏠 프로세스 광역 스캔 시작: 타 프로세스 간섭 여부 확인")

        if not self.upid_n or not self.upid_s:
            return "⚠️ 오류: 대상 패키지의 UPID를 찾을 수 없습니다."

        # 1. SQL: 모든 프로세스의 CPU 점유 시간 합산 (상위 30개)
        process_sql = """
        SELECT 
            p.name as proc_name,
            SUM(s.dur) / 1e6 as cpu_ms
        FROM sched s
        JOIN thread t USING (utid)
        JOIN process p USING (upid)
        GROUP BY p.upid
        ORDER BY cpu_ms DESC
        LIMIT 30
        """

        # 데이터 추출 (Normal/Slow 대조)
        p_n = self.tp_n.query(process_sql).as_pandas_dataframe()
        p_s = self.tp_s.query(process_sql).as_pandas_dataframe()

        # 2. 프로세스 레벨 Delta 분석
        proc_deltas = []
        all_proc_names = set(p_n["proc_name"]).union(set(p_s["proc_name"]))

        for name in all_proc_names:
            cpu_n = (
                p_n[p_n["proc_name"] == name]["cpu_ms"].values[0]
                if not p_n[p_n["proc_name"] == name].empty
                else 0
            )
            cpu_s = (
                p_s[p_s["proc_name"] == name]["cpu_ms"].values[0]
                if not p_s[p_s["proc_name"] == name].empty
                else 0
            )
            delta = cpu_s - cpu_n

            # 변화가 없더라도 '현재 CPU 사용량(cpu_s)'을 함께 기록해서 정렬의 기준으로 삼습니다.
            proc_deltas.append(
                {
                    "name": name,
                    "delta": delta,
                    "cpu_usage": cpu_s,  # 현재 상태를 보여주기 위한 백업 데이터
                }
            )

        # Delta 순 정렬
        proc_deltas.sort(key=lambda x: x["delta"], reverse=True)

        # 3. [핵심] Positive Ratio 계산 (지연 지분)
        total_increase = sum(d["delta"] for d in proc_deltas if d["delta"] > 0)
        denominator = (
            total_increase
            if total_increase > 0
            else sum(abs(d["delta"]) for d in proc_deltas)
        )

        # 4. 마크다운 리포트 생성 (Top 5 + Others)
        top_5 = proc_deltas[:5]
        others = proc_deltas[5:]
        others_delta = sum(d["delta"] for d in others)

        md = f"### 🏠 Process Stats (Total Inc: +{total_increase:.2f}ms)\n"
        md += "| Rank | Process Name | Delta | Ratio | Status |\n"
        md += "| :--- | :--- | :--- | :--- | :--- |\n"

        for i, d in enumerate(top_5, 1):
            ratio = (
                (d["delta"] / denominator * 100)
                if denominator > 0 and d["delta"] > 0
                else 0
            )

            # STABLE 로직 적용 (±0.1ms)
            if d["delta"] > 0.1:
                status = "🔴 INC"
            elif d["delta"] < -0.1:
                status = "🟢 DEC"
            else:
                status = "⚪ STABLE"

            md += f"| {i} | {d['name']} | {d['delta']:+.2f}ms | {ratio:.1f}% | {status} |\n"

        if others:
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            md += f"| **기타** | **나머지 {len(others)}개 프로세스 합계** | **{others_delta:+.2f}ms** | {others_ratio:.1f}% | - |\n"

        # [수사관 가이드] AI에게 주는 결정적 힌트
        if total_increase > 0:
            # 우리 앱 이외의 프로세스가 상위권을 차지하고 있는지 체크
            external_inc = sum(
                d["delta"]
                for d in top_5
                if d["delta"] > 0 and self.target_package not in d["name"]
            )
            if (external_inc / total_increase) > 0.4:
                md += f"\n> ⚠️ **수사관 참고:** 타 프로세스의 CPU 점유 증가가 감지되었습니다. 시스템 부하(System Load)로 인한 지연일 가능성이 높습니다."
            else:
                md += "\n> ✅ **수사관 참고:** 외부 프로세스의 특이사항이 적습니다. 우리 앱 내부 로직에 집중하십시오."

        return md

    def trace_binder_calls(self):
        print(f"📞 바인더 통신 수사 시작: {self.package}의 IPC 분석")

        if not self.upid_n or not self.upid_s:
            return "⚠️ 오류: 대상 패키지의 UPID를 찾을 수 없습니다."

        # 1. SQL: 바인더 거래 및 AIDL 인터페이스 추출
        binder_sql = """
        SELECT 
            s.name,
            COUNT(*) as call_count,
            SUM(s.dur) / 1e6 as dur_ms
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        WHERE t.upid = {actual_upid} 
        AND (
            s.name LIKE '%binder%' 
            OR s.name LIKE '%AIDL%' 
            OR s.name LIKE '%aidl%' 
            OR s.name LIKE 'transact%'
        )
        GROUP BY s.name
        ORDER BY dur_ms DESC
        LIMIT 50
        """

        # UPID 바인딩 및 데이터 추출
        b_n = self.tp_n.query(
            binder_sql.format(actual_upid=self.upid_n)
        ).as_pandas_dataframe()
        b_s = self.tp_s.query(
            binder_sql.format(actual_upid=self.upid_s)
        ).as_pandas_dataframe()

        # 2. 바인더 Delta 분석
        binder_deltas = []
        all_calls = set(b_n["name"]).union(set(b_s["name"]))

        for name in all_calls:
            row_n = b_n[b_n["name"] == name]
            row_s = b_s[b_s["name"] == name]

            dur_n = row_n["dur_ms"].values[0] if not row_n.empty else 0
            dur_s = row_s["dur_ms"].values[0] if not row_s.empty else 0
            cnt_n = row_n["call_count"].values[0] if not row_n.empty else 0
            cnt_s = row_s["call_count"].values[0] if not row_s.empty else 0

            delta_ms = dur_s - dur_n
            delta_cnt = cnt_s - cnt_n

            # 🚀 모든 호출을 일단 다 담습니다 (정렬을 위해 dur_s 저장)
            binder_deltas.append(
                {
                    "name": name,
                    "delta": delta_ms,
                    "delta_cnt": delta_cnt,
                    "dur_s": dur_s,
                }
            )

        # 🚀 [핵심 정렬] 1순위: 지연 발생(Delta), 2순위: 현재 점유 시간(dur_s)
        binder_deltas.sort(key=lambda x: (x["delta"], x["dur_s"]), reverse=True)

        # 3. Positive Ratio 계산
        total_increase = sum(d["delta"] for d in binder_deltas if d["delta"] > 0)
        denominator = (
            total_increase
            if total_increase > 0
            else sum(abs(d["delta"]) for d in binder_deltas)
        )

        # 4. 마크다운 리포트 생성
        md = f"### 📞 Binder Analysis (Total Inc: +{total_increase:.2f}ms)\n"
        md += "| Rank | Binder Call Name | Delta | Count Δ | Ratio | Status |\n"
        md += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"

        for i, d in enumerate(binder_deltas[:5], 1):
            ratio = (
                (d["delta"] / denominator * 100)
                if denominator > 0 and d["delta"] > 0
                else 0
            )

            # STABLE 로직 (±0.1ms)
            if d["delta"] > 0.1:
                status = "🔴 INC"
            elif d["delta"] < -0.1:
                status = "🟢 DEC"
            else:
                status = "⚪ STABLE"

            cnt_str = f"{d['delta_cnt']:+d}" if d["delta_cnt"] != 0 else "0"
            md += f"| {i} | {d['name']} | {d['delta']:+.2f}ms | {cnt_str} | {ratio:.1f}% | {status} |\n"

        if len(binder_deltas) > 5:
            others = binder_deltas[5:]
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_delta_sum = sum(d["delta"] for d in others)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            md += f"| **기타** | **나머지 {len(others)}개 호출 합계** | **{others_delta_sum:+.2f}ms** | - | {others_ratio:.1f}% | - |\n"

        # [수사관 가이드]
        if total_increase <= 0:
            md += "\n> 💡 **수사관 참고:** 바인더 통신 패턴이 매우 일정합니다. 통신 지연(IPC Delay)은 이번 사건의 원인이 아닐 가능성이 높습니다."
        elif any(d["delta_cnt"] > 10 for d in binder_deltas[:5]):
            md += "\n> ⚠️ **수사관 참고:** 호출 횟수가 급증한 'Chatty Binder' 현상이 탐지되었습니다. 로직 최적화가 필요할 수 있습니다."

        return md

    def check_thread_scheduling(self, thread_name="auto"):
        # 1. 수사 대상 스레드 확정 (Tool 1에서 찾은 범인 혹은 수동 지정)
        target = (
            thread_name
            if thread_name != "auto"
            else (self.top_threads[0] if self.top_threads else "Unknown")
        )
        print(f"⏳ 스케줄링 최종 수사: {target} 상태 분석")

        if not self.upid_n or not self.upid_s:
            return "⚠️ 오류: 대상 패키지의 UPID를 찾을 수 없습니다."

        # 2. SQL: 스레드 상태별 시간 합산
        # thread_state 테이블을 뒤져서 Running, R(Runnable), S(Sleeping) 등을 추출합니다.
        sched_sql = f"""
        SELECT 
            ts.state, 
            SUM(ts.dur) / 1e6 as dur_ms
        FROM thread_state ts
        JOIN thread t USING (utid)
        WHERE t.upid = {{actual_upid}} AND t.name = '{target}'
        GROUP BY ts.state
        ORDER BY dur_ms DESC
        """

        s_n = self.tp_n.query(
            sched_sql.format(actual_upid=self.upid_n)
        ).as_pandas_dataframe()
        s_s = self.tp_s.query(
            sched_sql.format(actual_upid=self.upid_s)
        ).as_pandas_dataframe()

        # 3. 상태별 Delta 분석
        state_deltas = []
        all_states = set(s_n["state"]).union(set(s_s["state"]))

        for state in all_states:
            dur_n = (
                s_n[s_n["state"] == state]["dur_ms"].values[0]
                if not s_n[s_n["state"] == state].empty
                else 0
            )
            dur_s = (
                s_s[s_s["state"] == state]["dur_ms"].values[0]
                if not s_s[s_s["state"] == state].empty
                else 0
            )
            delta = dur_s - dur_n

            state_deltas.append({"name": state, "delta": delta, "dur_s": dur_s})

        # 🚀 [핵심 정렬] 1순위: Delta(증가폭), 2순위: 현재 점유 시간
        state_deltas.sort(key=lambda x: (x["delta"], x["dur_s"]), reverse=True)

        # 4. Positive Ratio 계산
        total_increase = sum(d["delta"] for d in state_deltas if d["delta"] > 0)
        denominator = (
            total_increase
            if total_increase > 0
            else (sum(abs(d["delta"]) for d in state_deltas) or 1)
        )

        # 5. 마크다운 리포트 생성
        md = (
            f"### ⏳ Thread Scheduling: {target} (Total Inc: +{total_increase:.2f}ms)\n"
        )
        md += "| Rank | Thread State | Delta | Ratio | Status |\n"
        md += "| :--- | :--- | :--- | :--- | :--- |\n"

        state_map = {
            "R": "Runnable (Wait CPU)",
            "Running": "Running (Active)",
            "S": "Sleeping (Blocked/Wait)",
            "D": "Disk Wait (I/O)",
            "R+": "Runnable (Preempted)",
        }

        for i, d in enumerate(state_deltas[:5], 1):
            ratio = (d["delta"] / denominator * 100) if d["delta"] > 0 else 0
            status = (
                "🔴 INC"
                if d["delta"] > 0.1
                else ("🟢 DEC" if d["delta"] < -0.1 else "⚪ STABLE")
            )

            friendly_name = state_map.get(d["name"], d["name"])
            md += f"| {i} | {friendly_name} | {d['delta']:+.2f}ms | {ratio:.1f}% | {status} |\n"

        # [수사관 가이드]
        if total_increase <= 0.1:
            md += "\n> 💡 **수사관 참고:** 스레드 스케줄링이 매우 안정적입니다. CPU 경합으로 인한 지연은 발견되지 않았습니다."
        else:
            runnable_delta = next(
                (d["delta"] for d in state_deltas if d["name"] == "R"), 0
            )
            if runnable_delta > (total_increase * 0.4):
                md += "\n> ⚠️ **수사관 참고:** Runnable(대기) 비중이 높습니다. 다른 프로세스가 CPU를 점유 중인지 확인하십시오."

        return md

    def check_lock_contention(self):
        print(f"🔒 원 경합(Lock) 최종 수사: {self.package}")

        if not self.upid_n or not self.upid_s:
            return "⚠️ 오류: 대상 패키지의 UPID를 찾을 수 없습니다."

        # 1. SQL: 수사망 확대 (LOWER 적용 및 다양한 락 명칭 포함)
        lock_sql = """
        SELECT 
            s.name as lock_name, 
            COUNT(*) as wait_count,
            SUM(s.dur) / 1e6 as dur_ms
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        WHERE t.upid = {actual_upid} 
        AND (
            LOWER(s.name) LIKE '%monitor contention%' 
            OR LOWER(s.name) LIKE '%waiting on condition%'
            OR LOWER(s.name) LIKE '%lock contention%'
        )
        GROUP BY s.name
        ORDER BY dur_ms DESC
        LIMIT 50
        """

        l_n = self.tp_n.query(
            lock_sql.format(actual_upid=self.upid_n)
        ).as_pandas_dataframe()
        l_s = self.tp_s.query(
            lock_sql.format(actual_upid=self.upid_s)
        ).as_pandas_dataframe()

        # 2. Lock Delta 분석
        lock_deltas = []
        all_locks = set(l_n["lock_name"]).union(set(l_s["lock_name"]))

        for name in all_locks:
            row_n = l_n[l_n["lock_name"] == name]
            row_s = l_s[l_s["lock_name"] == name]

            dur_n = row_n["dur_ms"].values[0] if not row_n.empty else 0
            dur_s = row_s["dur_ms"].values[0] if not row_s.empty else 0
            cnt_n = row_n["wait_count"].values[0] if not row_n.empty else 0
            cnt_s = row_s["wait_count"].values[0] if not row_s.empty else 0

            delta_ms = dur_s - dur_n
            delta_cnt = cnt_s - cnt_n

            # 🚀 모든 락을 담습니다 (정렬을 위해 dur_s 저장)
            lock_deltas.append(
                {
                    "name": name,
                    "delta": delta_ms,
                    "delta_cnt": delta_cnt,
                    "dur_s": dur_s,
                }
            )

        # 🚀 [핵심 정렬] 1순위: 지연 발생(Delta), 2순위: 현재 점유 시간(dur_s)
        lock_deltas.sort(key=lambda x: (x["delta"], x["dur_s"]), reverse=True)

        # 3. Positive Ratio 계산
        total_increase = sum(d["delta"] for d in lock_deltas if d["delta"] > 0)
        denominator = (
            total_increase
            if total_increase > 0
            else sum(abs(d["delta"]) for d in lock_deltas)
        )

        # 4. 마크다운 리포트 생성
        md = f"### 🔒 Lock Contention (Total Inc: +{total_increase:.2f}ms)\n"
        md += "| Rank | Lock Detail / Owner | Delta | Wait Δ | Ratio | Status |\n"
        md += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"

        # 상위 5개 락 출력
        for i, d in enumerate(lock_deltas[:5], 1):
            ratio = (
                (d["delta"] / denominator * 100)
                if denominator > 0 and d["delta"] > 0
                else 0
            )

            if d["delta"] > 0.1:
                status = "🔴 INC"
            elif d["delta"] < -0.1:
                status = "🟢 DEC"
            else:
                status = "⚪ STABLE"

            cnt_str = f"{d['delta_cnt']:+d}" if d["delta_cnt"] != 0 else "0"
            display_name = d["name"].replace(
                "monitor contention with owner ", "Owner: "
            )

            md += f"| {i} | {display_name} | {d['delta']:+.2f}ms | {cnt_str} | {ratio:.1f}% | {status} |\n"

        if others := lock_deltas[5:]:
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_delta_sum = sum(d["delta"] for d in others)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            md += f"| **기타** | **나머지 {len(others)}개 경합 합계** | **{others_delta_sum:+.2f}ms** | - | {others_ratio:.1f}% | - |\n"

        # [수사관 가이드]
        if total_increase <= 0:
            md += "\n> 💡 **수사관 참고:** 자원 경합 패턴이 일정합니다. 내부 로직 최적화보다는 CPU 스케줄링(4번)이나 메모리(6번) 조사를 권장합니다."

        return md

    def check_memory_gc(self):
        print(f"🧹 메모리 및 GC 최종 수사: {self.package}")

        if not self.upid_n or not self.upid_s:
            return "⚠️ 오류: 대상 패키지의 UPID를 찾을 수 없습니다."

        # 1. SQL: GC 및 메모리 할당 관련 슬라이스 추출 (수사망 확대)
        memory_sql = """
        SELECT 
            s.name as event_name, 
            COUNT(*) as event_count,
            SUM(s.dur) / 1e6 as dur_ms
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        WHERE t.upid = {actual_upid} 
        AND (
            LOWER(s.name) LIKE '%gc%' 
            OR LOWER(s.name) LIKE '%alloc%'
            OR LOWER(s.name) LIKE '%free%'
            OR LOWER(s.name) LIKE '%mem%'
        )
        GROUP BY s.name
        ORDER BY dur_ms DESC
        LIMIT 50
        """

        m_n = self.tp_n.query(
            memory_sql.format(actual_upid=self.upid_n)
        ).as_pandas_dataframe()
        m_s = self.tp_s.query(
            memory_sql.format(actual_upid=self.upid_s)
        ).as_pandas_dataframe()

        # 2. Memory Delta 분석
        mem_deltas = []
        all_events = set(m_n["event_name"]).union(set(m_s["event_name"]))

        for name in all_events:
            row_n = m_n[m_n["event_name"] == name]
            row_s = m_s[m_s["event_name"] == name]

            dur_n = row_n["dur_ms"].values[0] if not row_n.empty else 0
            dur_s = row_s["dur_ms"].values[0] if not row_s.empty else 0
            cnt_n = row_n["event_count"].values[0] if not row_n.empty else 0
            cnt_s = row_s["event_count"].values[0] if not row_s.empty else 0

            delta_ms = dur_s - dur_n
            delta_cnt = cnt_s - cnt_n

            # 🚀 상시 노출을 위해 모든 이벤트를 담고, 현재 점유 시간(dur_s)을 기록
            mem_deltas.append(
                {
                    "name": name,
                    "delta": delta_ms,
                    "delta_cnt": delta_cnt,
                    "dur_s": dur_s,
                }
            )

        # 🚀 [핵심 정렬] 1순위: 지연 발생(Delta), 2순위: 현재 점유 시간(dur_s)
        mem_deltas.sort(key=lambda x: (x["delta"], x["dur_s"]), reverse=True)

        # 3. Positive Ratio 계산
        total_increase = sum(d["delta"] for d in mem_deltas if d["delta"] > 0)
        denominator = (
            total_increase
            if total_increase > 0
            else sum(abs(d["delta"]) for d in mem_deltas)
        )

        # 4. 마크다운 리포트 생성
        md = f"### 🧹 Memory & GC (Total Inc: +{total_increase:.2f}ms)\n"
        md += "| Rank | Memory Event | Delta | Count Δ | Ratio | Status |\n"
        md += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"

        for i, d in enumerate(mem_deltas[:5], 1):
            ratio = (
                (d["delta"] / denominator * 100)
                if denominator > 0 and d["delta"] > 0
                else 0
            )

            # STABLE 로직 (±0.1ms)
            if d["delta"] > 0.1:
                status = "🔴 INC"
            elif d["delta"] < -0.1:
                status = "🟢 DEC"
            else:
                status = "⚪ STABLE"

            cnt_str = f"{d['delta_cnt']:+d}" if d["delta_cnt"] != 0 else "0"
            md += f"| {i} | {d['name']} | {d['delta']:+.2f}ms | {cnt_str} | {ratio:.1f}% | {status} |\n"

        if len(mem_deltas) > 5:
            others = mem_deltas[5:]
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_delta_sum = sum(d["delta"] for d in others)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            md += f"| **기타** | **나머지 {len(others)}개 이벤트 합계** | **{others_delta_sum:+.2f}ms** | - | {others_ratio:.1f}% | - |\n"

        # [수사관 가이드]
        if total_increase <= 0:
            md += "\n> 💡 **수사관 참고:** 메모리 관리 작업이 매우 안정적입니다. GC로 인한 중단 현상(Stop-the-world)은 발견되지 않았습니다."
        elif total_increase > 50:
            md += "\n> ⚠️ **수사관 참고:** 과도한 메모리 할당이나 GC 지연이 감지되었습니다. 힙(Heap) 덤프 분석을 권장합니다."

        return md

    def execute_custom_sql(self, query, reason):
        print(f"🕵️ 특별 수사(Custom) 개시: {reason}")

        if not self.upid_n or not self.upid_s:
            return "⚠️ 오류: 대상 패키지의 UPID를 찾을 수 없습니다."

        try:
            # 1. 쿼리 포맷팅 및 실행
            f_query_n = query.format(upid=self.upid_n, actual_upid=self.upid_n)
            f_query_s = query.format(upid=self.upid_s, actual_upid=self.upid_s)

            df_n = self.tp_n.query(f_query_n).as_pandas_dataframe()
            df_s = self.tp_s.query(f_query_s).as_pandas_dataframe()

            if df_s.empty:
                return f"### 🕵️ Custom SQL Result: {reason}\n> ⚠️ 결과가 비어있습니다."

            # 2. 컬럼 식별 및 데이터 정제
            cols = df_s.columns.tolist()
            # 첫 번째 문자열 타입 컬럼 찾기 (없으면 첫 번째 컬럼)
            id_col = next((c for c in cols if df_s[c].dtype == "object"), cols[0])
            # 숫자로 변환 가능한 컬럼 중 첫 번째 찾기
            val_col = None
            for c in cols:
                if c == id_col:
                    continue
                try:
                    df_s[c] = pd.to_numeric(df_s[c])
                    df_n[c] = pd.to_numeric(df_n[c]) if not df_n.empty else 0
                    val_col = c
                    break
                except:
                    continue

            # 3. [중요] 숫자 컬럼을 못 찾았을 때의 안전장치
            if val_col is None:
                return f"### 🕵️ Custom SQL Result: {reason}\n" + df_s.head(
                    10
                ).to_markdown(index=False)

            # 4. 데이터 그룹화 (SQL에서 미처 안 했을 경우 대비)
            df_n = df_n.groupby(id_col)[val_col].sum().reset_index()
            df_s = df_s.groupby(id_col)[val_col].sum().reset_index()

            # 5. 대조 분석 (Merge)
            merged = df_s.merge(
                df_n, on=id_col, how="outer", suffixes=("_s", "_n")
            ).fillna(0)
            merged["delta"] = merged[f"{val_col}_s"] - merged[f"{val_col}_n"]

            # 정렬: 1순위 Delta(증가폭), 2순위 현재값
            merged = merged.sort_values(by=["delta", f"{val_col}_s"], ascending=False)

            # 6. 리포트 생성
            total_inc = merged[merged["delta"] > 0]["delta"].sum()
            denom = total_inc if total_inc > 0 else (merged["delta"].abs().sum() or 1)

            md = f"### 🕵️ Custom SQL Result: {reason} (Total Inc: +{total_inc:.2f})\n"
            md += f"| Rank | {id_col} | Delta ({val_col}) | Ratio | Status |\n"
            md += "| :--- | :--- | :--- | :--- | :--- |\n"

            top_5 = merged.head(5)
            for i, (_, row) in enumerate(top_5.iterrows(), 1):
                d = row["delta"]
                ratio = (d / denom * 100) if total_inc > 0 and d > 0 else 0

                if d > 0.1:
                    status = "🔴 INC"
                elif d < -0.1:
                    status = "🟢 DEC"
                else:
                    status = "⚪ STABLE"

                md += f"| {i} | {row[id_col]} | {d:+.2f} | {ratio:.1f}% | {status} |\n"

            if len(merged) > 5:
                others = merged.iloc[5:]
                o_delta = others["delta"].sum()
                o_ratio = (
                    (others[others["delta"] > 0]["delta"].sum() / denom * 100)
                    if total_inc > 0
                    else 0
                )
                md += f"| **기타** | **나머지 {len(others)}개 합계** | **{o_delta:+.2f}** | {o_ratio:.1f}% | - |\n"

            if total_inc <= 0.1:
                md += f"\n> 💡 **수사관 참고:** 유의미한 지연 증가가 감지되지 않았습니다. (Stable)"

            return md

        except Exception as e:
            import traceback

            return f"### 🕵️ Custom SQL Error\n> ❌ 오류 발생: {str(e)}\n```python\n{traceback.format_exc()}\n```"

    def profile_thread_functions(self, thread_name="auto"):
        # 1. 대상 스레드 확정 (Registry 활용)
        target = thread_name if thread_name != "auto" else self.top_threads[0]
        print(f"🔬 스레드 정밀 분석 시작: {target}")

        if not self.upid_n or not self.upid_s:
            return "⚠️ 오류: 대상 패키지의 UPID를 찾을 수 없습니다."

        # 2. SQL: 특정 스레드 내의 모든 함수 실행 시간 합산 (넉넉히 50개)
        func_sql_template = """
            SELECT 
                s.name, 
                SUM(s.dur) / 1e6 as dur_ms
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            WHERE t.upid = {actual_upid} AND t.name = '{t_name}'
            GROUP BY s.name
            ORDER BY dur_ms DESC
            LIMIT 50
            """

        # Normal 데이터 추출
        f_n = self.tp_n.query(
            func_sql_template.format(actual_upid=self.upid_n, t_name=target)
        ).as_pandas_dataframe()
        # Slow 데이터 추출
        f_s = self.tp_s.query(
            func_sql_template.format(actual_upid=self.upid_s, t_name=target)
        ).as_pandas_dataframe()

        # 3. 함수 레벨 Delta 분석
        func_deltas = []
        all_func_names = set(f_n["name"]).union(set(f_s["name"]))

        for name in all_func_names:
            dur_n = (
                f_n[f_n["name"] == name]["dur_ms"].values[0]
                if not f_n[f_n["name"] == name].empty
                else 0
            )
            dur_s = (
                f_s[f_s["name"] == name]["dur_ms"].values[0]
                if not f_s[f_s["name"] == name].empty
                else 0
            )
            delta = dur_s - dur_n

            # 변화가 없더라도 일단 모든 함수를 수집
            # 1. Delta 순으로 정렬 (범인 찾기용)
            # 2. Delta가 모두 0이라면 실행 시간(dur_s) 순으로 정렬 (현황 파악용)
            func_deltas.append({"name": name, "delta": delta, "dur": dur_s})

        # 정렬 로직
        func_deltas.sort(key=lambda x: (x["delta"], x["dur"]), reverse=True)

        # 4. [핵심] Positive Ratio 계산 (지연 지분)
        total_increase = sum(d["delta"] for d in func_deltas if d["delta"] > 0)
        denominator = (
            total_increase
            if total_increase > 0
            else sum(abs(d["delta"]) for d in func_deltas)
        )

        # 5. 마크다운 리포트 생성 (Top 5 + Others)
        top_5 = func_deltas[:5]
        others = func_deltas[5:]
        others_delta = sum(d["delta"] for d in others)

        md = f"### 🔬 Thread Profile: {target} (Total Inc: +{total_increase:.2f}ms)\n"
        md += "| Rank | Function Name | Delta | Ratio | Status |\n"
        md += "| :--- | :--- | :--- | :--- | :--- |\n"

        for i, d in enumerate(top_5, 1):
            ratio = (
                (d["delta"] / denominator * 100)
                if denominator > 0 and d["delta"] > 0
                else 0
            )

            # STABLE 로직 적용
            if d["delta"] > 0.1:
                status = "🔴 INC"
            elif d["delta"] < -0.1:
                status = "🟢 DEC"
            else:
                status = "⚪ STABLE"

            md += f"| {i} | {d['name']} | {d['delta']:+.2f}ms | {ratio:.1f}% | {status} |\n"

        if others:
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            md += f"| **기타** | **나머지 {len(others)}개 함수 합계** | **{others_delta:+.2f}ms** | {others_ratio:.1f}% | - |\n"

        # [Phase 2.5 가이드] AI에게 주는 결정적 힌트
        if total_increase > 0:
            if (
                sum(d["delta"] for d in top_5 if d["delta"] > 0) / total_increase
            ) < 0.5:
                md += "\n> ⚠️ **수사관 참고:** '기타' 비중이 높습니다. 특정 함수보다 Binder/Lock 등 외부 요인 수색을 권장합니다."
            else:
                md += "\n> ✅ **수사관 참고:** 특정 함수에 지연이 집중됨. 해당 함수의 내부 로직 혹은 Custom SQL 수사를 권장합니다."

        return md
