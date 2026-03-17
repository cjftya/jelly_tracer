import pandas as pd
import numpy as np
from perfetto.trace_processor import TraceProcessor


class CommonAPI:
    def __init__(self, normal_trace_path, slow_trace_path, package_name):
        self.tp_n = TraceProcessor(file_path=normal_trace_path)
        self.tp_s = TraceProcessor(file_path=slow_trace_path)
        self.package = package_name
        self.upid_n = self._get_upid(self.tp_n)
        self.upid_s = self._get_upid(self.tp_s)

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

    def profile_thread_functions(self, thread_name="auto", out_limit=3):
        # 1. 대상 스레드 확정 (Registry 활용)
        target = thread_name if thread_name != "auto" else "auto"
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
            AND t.name LIKE '{t_name}%'
            AND s.parent_id IS NULL
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

        top_list = func_deltas[:out_limit]
        for i, d in enumerate(top_list, 1):
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

        if others := func_deltas[out_limit:]:
            others_delta = sum(d["delta"] for d in others)
            others_pos_delta = sum(d["delta"] for d in others if d["delta"] > 0)
            others_ratio = (
                (others_pos_delta / denominator * 100) if denominator > 0 else 0
            )
            md += f"| **Others** | **Sum of remaining {len(others)} functions** | **{others_delta:+.2f}ms** | {others_ratio:.1f}% | - |\n"
        return md

    def check_thread_scheduling(self, thread_name="auto", out_limit=3):
        # 1. 수사 대상 스레드 확정 (Tool 1에서 찾은 범인 혹은 수동 지정)
        target = thread_name if thread_name != "auto" else "auto"
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
        WHERE t.upid = {{actual_upid}} AND t.name LIKE '{target}%'
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

        for i, d in enumerate(state_deltas[:out_limit], 1):
            ratio = (d["delta"] / denominator * 100) if d["delta"] > 0 else 0
            status = (
                "🔴 INC"
                if d["delta"] > 0.1
                else ("🟢 DEC" if d["delta"] < -0.1 else "⚪ STABLE")
            )

            friendly_name = state_map.get(d["name"], d["name"])
            md += f"| {i} | {friendly_name} | {d['delta']:+.2f}ms | {ratio:.1f}% | {status} |\n"

        return md

    