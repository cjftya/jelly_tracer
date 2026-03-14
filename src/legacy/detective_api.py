import pandas as pd
import numpy as np
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

        self.top_threads = []
        self.total_target_delta = 0
        self.analysis_start_n = 0
        self.analysis_end_n = 0
        self.analysis_start_s = 0
        self.analysis_end_s = 0

        self.utid_n = None
        self.utid_s = None

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
        # keyword : 패키지명 또는 스레드/프로세스명
        print(f"🔎 시스템 광역 스캔 및 델타 분석 시작 (Target: {keyword})")

        # 1. SQL 정의 (지휘관님의 기존 쿼리 유지, 데이터는 넉넉히 50개까지 수집)
        milestone_sql = """
        SELECT name,
        CAST(SUM(dur) / 1e6 AS FLOAT) as total_dur_ms,
        COALESCE(MIN(ts), 0) as min_ts, 
        COALESCE(MAX(ts + CASE WHEN dur > 0 THEN dur ELSE 0 END), 0) as max_ts
        FROM slice
        WHERE name IN ('bindApplication', 'activityStart', 'Choreographer#doFrame', 
                    'reportFullyDrawn', 'PostFork', 'viewVisibility')
        AND depth = 0
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

        if not m_n.empty and m_n['min_ts'].any():
            self.analysis_start_n = m_n[m_n['min_ts'] > 0]['min_ts'].min()
            self.analysis_end_n = m_n[m_n['max_ts'] > 0]['max_ts'].max()
        else:
            res = self.tp_n.query("SELECT MIN(ts) as s, MAX(ts) as e FROM slice").as_pandas_dataframe()
            self.analysis_start_n, self.analysis_end_n = res.iloc[0, 0], res.iloc[0, 1]

        if not m_s.empty and m_s['min_ts'].any():
            self.analysis_start_s = m_s[m_s['min_ts'] > 0]['min_ts'].min()
            self.analysis_end_s = m_s[m_s['max_ts'] > 0]['max_ts'].max()
        else:
            res = self.tp_s.query("SELECT MIN(ts) as s, MAX(ts) as e FROM slice").as_pandas_dataframe()
            self.analysis_start_s, self.analysis_end_s = res.iloc[0, 0], res.iloc[0, 1]

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

        # [Latency Coverage 계산을 위한 전체 합계]
        v_n_total = m_n["total_dur_ms"].sum() # Normal 마일스톤 합계
        v_s_total = m_s["total_dur_ms"].sum() # Slow 마일스톤 합계
        self.total_target_delta = v_s_total - v_n_total
        
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
            f"\n### 🧵 Thread CPU Delta (Local Δ: +{total_increase:.2f}ms)\n"
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
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            thread_md += f"| **Others** | **Sum of remaining {len(others)} threads** | **{others_delta:+.2f}ms** | {others_ratio:.1f}% | - |\n"

        if total_increase <= 0.1:
                thread_md += "\n> 💡 **Insight**: No CPU increase. Pivot to **Binder (Tool 3)**, **Lock (Tool 5)**, or **System Load**."

        return milestone_md + thread_md

    def check_process_cpu(self):
        print("🏠 프로세스 광역 스캔 시작: 타 프로세스 간섭 여부 확인")

        if not self.upid_n or not self.upid_s:
            return "⚠️ Error: not found UPID for the target package."

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

        md = f"### 🏠 Process Stats (Local Δ: +{total_increase:.2f}ms)\n"
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
            md += f"| **Others** | **Sum of remaining {len(others)} processes** | **{others_delta:+.2f}ms** | {others_ratio:.1f}% | - |\n"

        if total_increase > 0.1:
            external_inc = sum(
                d["delta"]
                for d in top_5
                if d["delta"] > 0 and self.target_package not in d["name"]
            )
            external_ratio = (external_inc / total_increase) * 100
            if external_ratio > 40:
                md += f"\n> ⚠️ **Insight**: External CPU Load High ({external_ratio:.1f}% of Local Δ). Suspect **CPU Starvation** by background tasks."
            else:
                md += f"\n> ✅ **Insight**: External interference low ({external_ratio:.1f}%). Root cause is likely inside **Target Package**."
        else:
            md += "\n> 💡 **Insight**: CPU Load stable. No external interference."

        return md + self._get_coverage_hint(total_increase)

    def trace_binder_calls(self):
        print(f"📞 바인더 통신 수사 시작: {self.package}의 IPC 분석")

        if not self.upid_n or not self.upid_s:
            return "⚠️ Error: not found UPID for the target package."

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
            s.name LIKE 'transact%'
            OR s.name LIKE 'JavaBinder:%'
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
        md = f"### 📞 Binder Analysis (Local Δ: +{total_increase:.2f}ms)\n"
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
            md += f"| **Others** | **Sum of remaining {len(others)} calls** | **{others_delta_sum:+.2f}ms** | - | {others_ratio:.1f}% | - |\n"

        if total_increase <= 0.1:
            md += "\n> 💡 **Insight**: Binder patterns stable. IPC is not the driver."
        elif any(d["delta_cnt"] > 10 for d in binder_deltas[:5]):
            md += "\n> ⚠️ **Insight**: 'Chatty Binder' detected (High call count Δ). Audit for redundant IPCs."

        return md + self._get_coverage_hint(total_increase)

    def check_thread_scheduling(self, thread_name="auto"):
        # 1. 수사 대상 스레드 확정 (Tool 1에서 찾은 범인 혹은 수동 지정)
        target = (
            thread_name
            if thread_name != "auto"
            else (self.top_threads[0] if self.top_threads else "Unknown")
        )
        print(f"⏳ 스케줄링 최종 수사: {target} 상태 분석")

        if not self.upid_n or not self.upid_s:
            return "⚠️ Error: not found UPID for the target package."

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
            f"### ⏳ Thread Scheduling: {target} (Local Δ: +{total_increase:.2f}ms)\n"
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

        if total_increase <= 0.1:
            md += "\n> 💡 **Insight**: Scheduling states are highly stable. Shift focus to internal application logic (Tool 7) or IPC/Binder transactions (Tool 3) rather than CPU contention."
        else:
            wait_cpu_delta = sum(
                d["delta"] for d in state_deltas if d["name"] in ["R", "R+"]
            )
            if total_increase <= 0.1:
                md += "\n> 💡 **Insight**: Scheduling stable. Pivot to **Tool 7 (Logic)** or **Tool 3 (IPC)**."
            elif wait_cpu_delta > (total_increase * 0.4):
                md += f"\n> ⚠️ **Insight**: CPU Wait high ({wait_cpu_delta/total_increase*100:.1f}% of Local Δ). Suspect **Contention** or **Low Clock**."
            elif any(d["name"] == "D" and d["delta"] > 10 for d in state_deltas):
                md += "\n> 🚨 **Insight**: **D-state** (I/O Wait) detected. Check Disk I/O or Memory Thrashing."

        return md + self._get_coverage_hint(total_increase)

    def check_lock_contention(self):
        print(f"🔒 자원 경합(Lock) 정밀 수사 시작: {self.package}")

        if not self.upid_n or not self.upid_s:
            return "⚠️ Error: not found UPID for the target package."

        # 1. SQL: depth=0을 제외하여 모든 경합 데이터를 수집 (Lock은 대개 depth > 0임)
        # LIKE 문을 사용하여 성능을 높이고 ART(Android Runtime)의 표준 경합 명칭을 타겟팅합니다.
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
            s.name LIKE 'monitor contention%' 
            OR s.name LIKE 'waiting on condition%'
            OR s.name LIKE 'Lock contention%'
        )
        GROUP BY s.name
        ORDER BY dur_ms DESC
        LIMIT 50
        """

        # 데이터 추출 (Normal / Slow)
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

            lock_deltas.append(
                {
                    "name": name,
                    "delta": delta_ms,
                    "delta_cnt": delta_cnt,
                    "dur_s": dur_s,
                }
            )

        # Delta 순 정렬 (지연 발생 우선)
        lock_deltas.sort(key=lambda x: (x["delta"], x["dur_s"]), reverse=True)

        # 3. Ratio 계산을 위한 분모 설정
        total_increase = sum(d["delta"] for d in lock_deltas if d["delta"] > 0)
        denominator = (
            total_increase
            if total_increase > 0
            else sum(abs(d["delta"]) for d in lock_deltas)
        )

        # 4. 마크다운 리포트 생성
        md = f"### 🔒 Lock Contention (Local Δ: +{total_increase:.2f}ms)\n"
        md += "| Rank | Lock Detail / Owner | Delta | Wait Δ | Ratio | Status |\n"
        md += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"

        for i, d in enumerate(lock_deltas[:5], 1):
            ratio = (
                (d["delta"] / denominator * 100)
                if denominator > 0 and d["delta"] > 0
                else 0
            )

            # 상태 판별
            if d["delta"] > 0.1:
                status = "🔴 INC"
            elif d["delta"] < -0.1:
                status = "🟢 DEC"
            else:
                status = "⚪ STABLE"

            # Owner 정보 가공 (가독성 증대)
            display_name = d["name"]
            if "monitor contention with owner " in display_name:
                # "with owner PortraitProc (123) at..." 부분에서 스레드명만 추출 시도
                try:
                    owner_part = display_name.split("with owner ")[1].split(" at ")[0]
                    display_name = f"⚠️ Owner: **{owner_part}**"
                except IndexError:
                    pass

            cnt_str = f"{d['delta_cnt']:+d}" if d["delta_cnt"] != 0 else "0"
            md += f"| {i} | {display_name} | {d['delta']:+.2f}ms | {cnt_str} | {ratio:.1f}% | {status} |\n"

        if len(lock_deltas) > 5:
            others = lock_deltas[5:]
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_delta_sum = sum(d["delta"] for d in others)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            md += f"| **Others** | **Sum of remaining {len(others)} contentions** | **{others_delta_sum:+.2f}ms** | - | {others_ratio:.1f}% | - |\n"

        if total_increase <= 0.1:
            md += "\n> 💡 **Insight**: Lock contention stable. Pivot to **Tool 7 (Logic)** or **Tool 3 (IPC)**."
        else:
            md += "\n> 🚨 **Insight**: Resource monopoly detected. Trace the **Owner** thread to find the blocker."

        return md + self._get_coverage_hint(total_increase)

    def check_memory_gc(self):
        print(f"🧹 메모리 및 GC 정밀 수사 시작: {self.package}")

        if not self.upid_n or not self.upid_s:
            return "⚠️ Error: not found UPID for the target package."

        # 1. SQL: depth = 0 필터를 통해 GC 세부 단계 중복 합산을 원천 차단합니다.
        # LOWER() 대신 표준 명칭 위주로 LIKE를 사용하여 저사양 환경의 쿼리 속도를 높입니다.
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
            s.name LIKE '%GC%' 
            OR s.name LIKE '%alloc%'
            OR s.name LIKE '%free%'
            OR s.name LIKE '%Mem%'
        )
        AND s.depth = 0
        GROUP BY s.name
        ORDER BY dur_ms DESC
        LIMIT 50
        """

        # 데이터 추출
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

            mem_deltas.append(
                {
                    "name": name,
                    "delta": delta_ms,
                    "delta_cnt": delta_cnt,
                    "dur_s": dur_s,
                }
            )

        # 정렬: 지연 증가(Delta) 최우선
        mem_deltas.sort(key=lambda x: (x["delta"], x["dur_s"]), reverse=True)

        # 3. Ratio 계산
        total_increase = sum(d["delta"] for d in mem_deltas if d["delta"] > 0)
        denominator = (
            total_increase
            if total_increase > 0
            else sum(abs(d["delta"]) for d in mem_deltas)
        )

        # 4. 마크다운 리포트 생성
        md = f"### 🧹 Memory & GC (Local Δ: +{total_increase:.2f}ms)\n"
        md += "| Rank | Memory Event | Delta | Count Δ | Ratio | Status |\n"
        md += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"

        for i, d in enumerate(mem_deltas[:5], 1):
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
            md += f"| {i} | {d['name']} | {d['delta']:+.2f}ms | {cnt_str} | {ratio:.1f}% | {status} |\n"

        if len(mem_deltas) > 5:
            others = mem_deltas[5:]
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_delta_sum = sum(d["delta"] for d in others)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            md += f"| **Others** | **Sum of remaining {len(others)} events** | **{others_delta_sum:+.2f}ms** | - | {others_ratio:.1f}% | - |\n"

        if total_increase <= 0.1:
            md += "\n> 💡 **Insight**: Memory efficient. GC is not the bottleneck."
        elif total_increase > 50:
            md += "\n> ⚠️ **Insight**: High GC delay. Suspect **Memory Pressure** (Object Churn) or **CPU Starvation**."

        return md + self._get_coverage_hint(total_increase)

    def execute_custom_sql(self, query, reason):
        print(f"🕵️ 특별 수사(Custom) 개시: {reason}")

        if not self.upid_n or not self.upid_s:
            return "⚠️ Error: not found UPID for the target package."

        try:
            # 1. 쿼리 포맷팅 및 실행
            f_query_n = query.format(upid=self.upid_n, actual_upid=self.upid_n)
            f_query_s = query.format(upid=self.upid_s, actual_upid=self.upid_s)

            df_n = self.tp_n.query(f_query_n).as_pandas_dataframe()
            df_s = self.tp_s.query(f_query_s).as_pandas_dataframe()

            if df_s.empty:
                return f"### 🕵️ Custom SQL Result: {reason}\n> ⚠️ Results are empty."

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

            md = f"### 🕵️ Custom SQL Result: {reason} (Local Δ: +{total_inc:.2f})\n"
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
                md += f"| **Others** | **Sum of remaining {len(others)} items** | **{o_delta:+.2f}** | {o_ratio:.1f}% | - |\n"

            if total_inc <= 0.1:
                md += f"\n> 💡 **Insight**: No significant increase found in this custom query."
            else:
                md += f"\n> 🔍 **Insight**: Custom investigation found **+{total_inc:.2f}** units of delay/drift."

            # 🚀 val_col 이름에 ms, dur 등이 포함되어 있는지 체크
            detected_unit = "ms" if any(x in val_col.lower() for x in ["ms", "dur", "time", "latency"]) else val_col
            return md + self._get_coverage_hint(total_inc, detected_unit)

        except Exception as e:
            return (
                f"### 🕵️ Custom SQL Error\n"
                f"> ❌ **Failed**: {str(e)}\n"
                f"> 💡 **Insight**: Check table/column names. "
                f"Always use **'s.depth=0'** for 'slice' table to avoid double-counting."
            )

    def profile_thread_functions(self, thread_name="auto"):
        # 1. 대상 스레드 확정 (Registry 활용)
        target = thread_name if thread_name != "auto" else self.top_threads[0]
        print(f"🔬 스레드 정밀 분석 시작: {target}")

        if not self.upid_n or not self.upid_s:
            return "⚠️ Error: not found UPID for the target package."

        # 2. SQL: s.depth = 0 필터를 통해 중복 계산을 원천 차단합니다.
        func_sql_template = """
            SELECT 
                s.name, 
                SUM(s.dur) / 1e6 as dur_ms
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            WHERE t.upid = {actual_upid} 
            AND t.name = '{t_name}'
            AND s.depth = 0
            GROUP BY s.name
            ORDER BY dur_ms DESC
            LIMIT 50
            """

        # 데이터 추출
        f_n = self.tp_n.query(
            func_sql_template.format(actual_upid=self.upid_n, t_name=target)
        ).as_pandas_dataframe()
        f_s = self.tp_s.query(
            func_sql_template.format(actual_upid=self.upid_s, t_name=target)
        ).as_pandas_dataframe()

        # 3. 함수 레벨 Delta 분석
        func_deltas = []
        all_func_names = set(f_n["name"]).union(set(f_s["name"]))

        for name in all_func_names:
            row_n = f_n[f_n["name"] == name]
            row_s = f_s[f_s["name"] == name]

            dur_n = row_n["dur_ms"].values[0] if not row_n.empty else 0
            dur_s = row_s["dur_ms"].values[0] if not row_s.empty else 0
            delta = dur_s - dur_n

            func_deltas.append({"name": name, "delta": delta, "dur": dur_s})

        # 정렬: 지연 발생(Delta) 순, 같으면 현재 점유율 순
        func_deltas.sort(key=lambda x: (x["delta"], x["dur"]), reverse=True)

        # 4. [핵심] Positive Ratio 계산 (지연 지분)
        total_increase = sum(d["delta"] for d in func_deltas if d["delta"] > 0)
        denominator = (
            total_increase
            if total_increase > 0
            else sum(abs(d["delta"]) for d in func_deltas)
        )

        # 5. 마크다운 리포트 생성
        md = f"### 🔬 Thread Profile: {target} (Local Δ: +{total_increase:.2f}ms)\n"
        md += "| Rank | Function Name | Delta | Ratio | Status |\n"
        md += "| :--- | :--- | :--- | :--- | :--- |\n"

        top_5 = func_deltas[:5]
        for i, d in enumerate(top_5, 1):
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

            md += f"| {i} | {d['name']} | {d['delta']:+.2f}ms | {ratio:.1f}% | {status} |\n"

        if others := func_deltas[5:]:
            others_delta = sum(d["delta"] for d in others)
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            md += f"| **Others** | **Sum of remaining {len(others)} functions** | **{others_delta:+.2f}ms** | {others_ratio:.1f}% | - |\n"

        if total_increase > 0:
            top_5_delta_sum = sum(d["delta"] for d in top_5 if d["delta"] > 0)
            top_5_ratio = top_5_delta_sum / total_increase

            if top_5_ratio < 0.5:
                md += f"\n> ⚠️ **Insight**: Delay fragmented ({top_5_ratio:.1f}% in Top 5). Suspect **External Interference** (Sched/IPC/Lock)."
            else:
                md += f"\n> ✅ **Insight**: Delay concentrated ({top_5_ratio:.1f}% in Top 5). Focus on **Internal Optimization** or **Custom SQL Deep-dive**."
        else:
            md += "\n> 💡 **Insight**: Function performance stable. No internal regression found."

        return md + self._get_coverage_hint(total_increase)

    def _get_coverage_hint(self, total_increase, unit="ms"):
        # 1. 단위가 ms가 아니면 Coverage 계산을 생략하거나 경고를 줍니다.
        if unit != "ms":
            return f"\n> ℹ️ **Metric Note**: Local Δ is measured in **{unit}**. (Latency Coverage not applicable)"

        if self.total_target_delta <= 0:
            # 정확도 문제가 아니라, 기준점이 없음을 알림
            return f"\n> ℹ️ **Coverage**: N/A (Total App Latency Δ is 0. Normal and Slow data are identical.)"

        # 2. ms인 경우에만 기존처럼 Coverage 계산
        cov = min(max((total_increase / self.total_target_delta) * 100, 0.0), 100.0)
        res = f"\n> **Latency Coverage: {cov:.1f}%**"
        
        if cov > 40: res += "\n> 🚨 **Critical**: Main culprit detected."
        elif cov > 15: res += "\n> ⚠️ **Warning**: Significant contribution."
        
        return res

    def get_device_info(self, normal_device_name="Normal Device", slow_device_name="Slow Device"):
        if not self.upid_n or not self.upid_s:
            return None

        def get_valid_range(tp, start, end):
            # np.isnan 또는 값이 None인 경우 체크
            if start is None or end is None or np.isnan(start) or np.isnan(end):
                # 마일스톤이 없으므로 트레이스의 절대 시작/끝 시간을 가져옴
                res = tp.query("SELECT MIN(ts) as s, MAX(ts) as e FROM slice").as_pandas_dataframe()
                return res['s'].iloc[0], res['e'].iloc[0]
            return start, end

        st_n, et_n = get_valid_range(self.tp_n, self.analysis_start_n, self.analysis_end_n)
        st_s, et_s = get_valid_range(self.tp_s, self.analysis_start_s, self.analysis_end_s)

        def get_main_utid(tp, upid):
            if pd.isna(upid) or upid is None: return -1
            query = f"SELECT utid FROM thread WHERE upid = {upid} LIMIT 1"
            res = tp.query(query).as_pandas_dataframe()
            return res['utid'].iloc[0] if not res.empty else -1

        utid_n = get_main_utid(self.tp_n, self.upid_n)
        utid_s = get_main_utid(self.tp_s, self.upid_s)

        def run_env_query(tp, start, end, utid):
            if pd.isna(start) or pd.isna(end): 
                return pd.DataFrame()

            info_sql = f"""
                WITH params AS (SELECT {start} AS start_ts, {end} AS end_ts, {utid} AS utid),
                avg_freq AS (
                    SELECT AVG(value) / 1000 AS mhz FROM counter
                    JOIN counter_track ON counter.track_id = counter_track.id
                    WHERE name = 'cpufreq' AND ts BETWEEN {start} AND {end}
                ),
                core_aff AS (
                    SELECT CASE WHEN cpu >= 4 THEN 'Big' ELSE 'Little' END AS core_type
                    FROM sched_slice WHERE utid = {utid} AND ts BETWEEN {start} AND {end}
                    GROUP BY core_type ORDER BY SUM(dur) DESC LIMIT 1
                ),
                sys_load AS (
                    SELECT (SUM(dur) * 100.0) / (({end} - {start}) * (SELECT COUNT(DISTINCT cpu) FROM sched_slice)) AS load_pct
                    FROM sched_slice WHERE ts BETWEEN {start} AND {end} AND utid != {utid}
                )
                SELECT 
                    COALESCE(CAST((SELECT mhz FROM avg_freq) AS INT), -1) AS avg_cpu_mhz,
                    COALESCE((SELECT core_type FROM core_aff), 'N/A') AS primary_core_type,
                    COALESCE(ROUND((SELECT load_pct FROM sys_load), 1), 0.0) AS total_sys_load_pct;
            """
            return tp.query(info_sql).as_pandas_dataframe()

        df_n = run_env_query(self.tp_n, self.analysis_start_n, self.analysis_end_n, utid_n)
        df_s = run_env_query(self.tp_s, self.analysis_start_s, self.analysis_end_s, utid_s)

        def finalize_df(df, type_name, device_name):
            if df.empty:
                df = pd.DataFrame([{'avg_cpu_mhz': -1, 'primary_core_type': 'N/A', 'total_sys_load_pct': 0.0}])
            df['type'], df['device'] = type_name, device_name
            df['avg_cpu_mhz'] = df['avg_cpu_mhz'].apply(lambda x: f"{x} MHz" if x > 0 else "N/A")
            df['total_sys_load_pct'] = df['total_sys_load_pct'].apply(lambda x: f"{x}%")
            return df

        return pd.concat([finalize_df(df_n, 'Normal', normal_device_name), 
                        finalize_df(df_s, 'Slow', slow_device_name)], ignore_index=True)
        


