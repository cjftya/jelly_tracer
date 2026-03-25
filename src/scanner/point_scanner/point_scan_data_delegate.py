import pandas as pd
import numpy as np
import json
from common_api import CommonAPI

class PointScanDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.utid_n = None  # Normal 트레이스의 타겟 스레드 ID
        self.utid_s = None  # Slow 트레이스의 타겟 스레드 ID
        self.ts_n = None    # Normal 트레이스 전체 시간 범위 [start, end]
        self.ts_s = None    # Slow 트레이스 전체 시간 범위 [start, end]
        self.target_thread = None
        self.output_callback = output_callback
        pd.set_option('future.no_silent_downcasting', True)

    def init(self, common_api, target_package):
        """두 트레이스 파일을 로드하고 분석을 위한 기초 시간 범위를 설정합니다."""
        self._common_api = common_api
        
        # 전체 트레이스의 시작과 끝을 구해야 나중에 스레드 점수를 매길 때 범위를 한정할 수 있습니다.
        self.ts_n = self.get_global_bounds("normal")
        self.ts_s = self.get_global_bounds("slow")
        
        if not self.ts_n or not self.ts_s:
            self.output_callback("⚠️ [Warning] Failed to retrieve global trace bounds.", True)

    def get_common_milestones(self):
        core_candidates = ['bindApplication', 'activityStart', 'activityResume']
        def fetch_milestones(mode):
            try:
                tp = self._common_api.get_trace_processor(mode)
                upid = self._common_api.get_upid(mode)
            except AttributeError:
                tp = self._common_api.tp_n if mode == "normal" else self._common_api.tp_s
                upid = self._common_api.upid_n if mode == "normal" else self._common_api.upid_s
            
            if tp is None or upid is None:
                return {}

            # 코어 마일스톤 추출 (프로세스 내 모든 스레드 대상)
            query = f"""
                SELECT name, ts 
                FROM slice 
                WHERE track_id IN (
                    SELECT id FROM thread_track 
                    WHERE utid IN (SELECT utid FROM thread WHERE upid = {upid})
                )
                AND name IN ({','.join([f"'{n}'" for n in core_candidates])})
                ORDER BY ts ASC
            """
            df = tp.query(query).as_pandas_dataframe()
            # 이름 중복 시 가장 먼저 나타난(가장 빠른) ts 선택
            m_dict = {row['name']: row['ts'] for _, row in df.drop_duplicates('name').iterrows()}
            
            # '화면 변화 없음' 지점 찾기 (Visual Idle)
            base_ts = m_dict.get('activityResume', 0)
            idle_query = f"""
                SELECT MAX(ts + dur) as last_ts
                FROM slice
                WHERE track_id IN (
                    SELECT id FROM thread_track 
                    WHERE utid IN (SELECT utid FROM thread WHERE upid = {upid})
                )
                AND (name LIKE 'Choreographer%' OR name LIKE 'doFrame%' OR name = 'traversal')
                AND ts > {base_ts}
            """
            idle_df = tp.query(idle_query).as_pandas_dataframe()
            
            # 결과가 [None]인 경우를 대비한 안전한 추출
            if not idle_df.empty:
                val = idle_df['last_ts'].iloc[0]
                if pd.notnull(val): # None이나 NaN이 아닐 때만 저장
                    m_dict['VisualComplete'] = int(val)
            
            return m_dict

        # 데이터 수집
        ms_n = fetch_milestones("normal")
        ms_s = fetch_milestones("slow")

        # 양쪽 공통 마일스톤 추출 (순서 유지)
        all_possible = core_candidates + ['VisualComplete']
        common_names = [n for n in all_possible if n in ms_n and n in ms_s]

        # 결과 판단
        if not common_names:
            if self.output_callback:
                self.output_callback("❌ [Error] No common milestones found between traces.", True)
            return None

        # 누락된 포인트에 대한 지능형 로그
        expected = set(all_possible)
        missing = expected - set(common_names)
        if missing and self.output_callback:
            if 'VisualComplete' in missing:
                self.output_callback("ℹ️ [Info] VisualComplete not found. Using last available marker.", True)
            important_missing = missing - {'VisualComplete'}
            if important_missing:
                self.output_callback(f"⚠️ [Warning] Missing core points: {list(important_missing)}", True)

        # 가장 첫 번째로 발견된 공통 마일스톤을 기준으로 정렬(Alignment)합니다.
        first_name = common_names[0]
        base_n = ms_n[first_name]
        base_s = ms_s[first_name]

        # 최종 리스트 조립
        final_milestones = []
        for name in all_possible:
            if name in ms_n and name in ms_s:
                # 1. 각 마일스톤이 기준점으로부터 얼마나 걸렸는지 계산 (ns -> ms)
                elapsed_n = (ms_n[name] - base_n) / 1e6
                elapsed_s = (ms_s[name] - base_s) / 1e6
                
                # 2. Normal 대비 Slow의 지연 시간(Delta) 계산
                # 이 값이 (+)이면 Slow가 그만큼 더 늦게 도달했다는 뜻입니다.
                delta_ms = elapsed_s - elapsed_n

                final_milestones.append({
                    "name": name,
                    "ts_n": ms_n[name],  # Normal 트레이스에서 그 사건이 터진 시각
                    "ts_s": ms_s[name],  # Slow 트레이스에서 그 사건이 터진 시각
                    "delta_ms": round(delta_ms, 2),  # [핵심] 누적 지연 시간
                    "elapsed_ms_s": round(elapsed_s, 2) # Slow 기준 진행 시간 (UI 표시용)
                })

        if self.output_callback:
            self.output_callback("\n🔍 [분석 구간 타임라인(Slow 기준)]", True)
            prev_delta = 0
            for m in final_milestones:
                elapsed = m['elapsed_ms_s']   # 현재 앱 실행 후 경과 시간
                curr_delta = m['delta_ms']     # 현재까지의 누적 지연
                step_delay = curr_delta - prev_delta  # 이전 지점 대비 추가된 지연
                
                # 1. 상태 메시지 및 마크 결정 (UX 최적화)
                if step_delay >= 30:
                    # 30ms 이상은 '집중 분석' 대상으로 분류
                    status = f"🔴 (정상 대비 +{step_delay:>5.1f}ms 지연 증가(이상) ↑)"
                elif step_delay > 5:
                    # 미세한 지연
                    status = f"⚠️ (정상 대비 +{step_delay:>5.1f}ms 지연 증가 ↑)"
                elif step_delay <= -5:
                    # 오히려 빨라진 경우 (최적화 구간)
                    status = f"✅ (정상 대비 {abs(step_delay):>5.1f}ms 단축!)"
                else:
                    # 차이가 거의 없는 경우
                    status = "(정상 수준)"

                # 2. 첫 지점은 기준점으로 표시
                if elapsed == 0:
                    status = "(분석 기준점)"

                # 3. 최종 출력 형식
                msg = f"📍 {m['name']:<18} : {elapsed:>8.1f}ms | {status}"
                self.output_callback(msg, True)
                prev_delta = curr_delta
        return final_milestones

    def identify_targets(self):
        self.output_callback("🔍 [Targeting] Identifying primary investigation targets...", True)
        
        # Slow 트레이스에서 가장 활발하거나 중요한(Choreographer 등) 스레드 후보 추출
        res_s = self.get_thread_candidates(self._common_api.tp_s, self._common_api.upid_s, self.ts_s)
        
        if res_s is None or res_s.empty:
            self.output_callback("🚨 [CRITICAL] No active threads found in SLOW trace.", True)
            return None, None, None

        # 가장 점수가 높은 스레드를 타겟으로 선정
        target_row_s = res_s.iloc[0]
        self.target_thread = target_row_s['thread_name']
        self.utid_s = int(target_row_s['utid'])
        
        self.output_callback(f"🕵️‍♂️ [Suspect Identified] '{self.target_thread}' (Score: {target_row_s['total_score']:.1f})", True)

        # Normal 트레이스에서도 동일한 이름의 스레드를 찾아 대조군(Baseline)으로 삼습니다.
        res_n = self.get_thread_candidates(self._common_api.tp_n, self._common_api.upid_n, self.ts_n)
        if res_n is None or res_n.empty:
            self.output_callback("🚨 [CRITICAL] Package data not found in NORMAL trace.", True)
            return None, None, None

        match_n = res_n[res_n['thread_name'] == self.target_thread]
        if match_n.empty:
            self._abort_investigation("Thread Name Mismatch", f"Target '{self.target_thread}' not found in NORMAL trace.")
            return None, None, None

        self.utid_n = int(match_n.iloc[0]['utid'])
        
        # 두 스레드의 구조적 유사도(Similarity)를 체크하여 비교 가능한 대상인지 검증합니다.
        similarity = self.check_thread_similarity(self.utid_n, self.utid_s)
        
        if similarity > 0.7:
            status = "✅ [High Confidence]"
        elif similarity > 0.35:
            status = "⚠️ [Moderate Confidence]"
        else:
            # 유사도가 너무 낮으면 비교 자체가 무의미하므로 수사를 중단합니다.
            self._abort_investigation("Structural Inconsistency", f"두 트레이스의 구조적 유사도가 너무 낮습니다 ({similarity:.1%}).")
            return None, None, None

        self.output_callback(f"{status} Baseline Matched. (Similarity: {similarity:.1%})", True)
        return self.utid_n, self.utid_s, self.target_thread

    def generate_point_scan_json(self, start_m, end_m):
        if not self.utid_s or not self.utid_n:
            return {"error": "Target threads not identified."}

        self.output_callback("🚀 [JSON Engine] 독립된 최악의 지연 구간 2곳을 추출 중...", True)

        start_ts_n, end_ts_n = start_m['ts_n'], end_m['ts_n']
        start_ts_s, end_ts_s = start_m['ts_s'], end_m['ts_s']
            
        # 1. 선정 로직 수정: 시간 범위 중첩을 체크하여 독립된 2개 사건 추출
        worst_roots = self._find_worst_slices(self.utid_n, self.utid_s, start_ts_n, end_ts_n, start_ts_s, end_ts_s)
        
        if not worst_roots:
            return {"worst_cases": []}

        worst_cases_data = []
        for i, root in enumerate(worst_roots):
            # 2. Depth 3까지 트리 구축 (기본 구조 유지)
            tree = self._build_json_tree_recursive(
                slice_id=root['id'],
                name=root['name'],
                parent_delta=root['delta'],
                depth=1,
                start_ts_n=start_ts_n, end_ts_n=end_ts_n,
                start_ts_s=start_ts_s, end_ts_s=end_ts_s 
            )
            
            worst_cases_data.append({
                "case_id": f"WC-00{i+1}",
                "issue": f"Regression in {root['name']} (Delta: {root['delta']:.1f}ms)",
                "total_duration": round(root['slow_ms'], 1),
                "tree": tree
            })

        return {"worst_cases": worst_cases_data}

    def _build_json_tree_recursive(self, slice_id, name, parent_delta, depth, start_ts_n, end_ts_n, start_ts_s, end_ts_s):
        if depth > 3: return None
        s_metrics = self._get_node_metrics_by_id(self._common_api.tp_s, self.utid_s, slice_id, start_ts_s, end_ts_s)
        n_metrics = self._get_node_metrics_by_name(self._common_api.tp_n, self.utid_n, name, start_ts_n, end_ts_n)
        if not s_metrics: return None
        delta = s_metrics['dur'] - (n_metrics['dur'] if n_metrics else 0)
        node_data = {
            "name": name, "delta_time": round(delta, 1), "self_time": round(s_metrics['self'], 1),
            "wait_time": round(s_metrics['wait'], 1), "impact_ratio": round(max(0, delta / parent_delta), 2) if parent_delta > 0 else 0.0,
            "children": [], "target_id": int(slice_id), "__internal_ts": s_metrics['raw_ts'],
            "__internal_dur": s_metrics['raw_dur'], "__internal_utid": int(self.utid_s)
        }
        if depth < 3:
            children_df = self._get_structural_children(self._common_api.tp_s, slice_id)
            if not children_df.empty:
                child_candidates = []
                for _, child in children_df.iterrows():
                    c_n_m = self._get_node_metrics_by_name(self._common_api.tp_n, self.utid_n, child['name'], start_ts_n, end_ts_n)
                    c_n_d = c_n_m['dur'] if c_n_m else 0
                    child_candidates.append({"id": int(child['id']), "name": child['name'], "delta": (child['dur']/1e6) - c_n_d})
                child_candidates.sort(key=lambda x: x['delta'], reverse=True)
                for c in child_candidates[:3]:
                    c_node = self._build_json_tree_recursive(c['id'], c['name'], delta, depth + 1, start_ts_n, end_ts_n, start_ts_s, end_ts_s)
                    if c_node: node_data["children"].append(c_node)
        return node_data

    def _find_worst_slices(self, utid_n, utid_s, start_ts_n, end_ts_n, start_ts_s, end_ts_s, limit=2):
        """
        [NEW] 시간 범위 포함 관계를 전수 조사하여 독립적인 Worst 2를 추출합니다.
        """
        self.output_callback("🛰️ [Deep Scan] 모든 계층에서 중복되지 않는 지연 구간 탐색...", True)
        
        # 1. Slow 트레이스의 타겟 구간 내 모든 슬라이스 수집
        query_s = f"""
            SELECT id, name, ts, dur, dur/1e6 as slow_ms
            FROM slice 
            WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid_s})
            AND ts >= {start_ts_s} AND (ts + dur) <= {end_ts_s}
        """
        df_all_s = self._common_api.tp_s.query(query_s).as_pandas_dataframe()
        if df_all_s.empty: return []

        # 2. Normal 트레이스에서 대조군 데이터 확보 (f-string 따옴표 에러 방지 처리)
        names_list = df_all_s['name'].unique()
        names_str = ", ".join(["'" + n.replace("'", "''") + "'" for n in names_list])
        query_n = f"""
            SELECT name, AVG(dur)/1e6 as avg_n 
            FROM slice 
            WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid_n}) 
            AND ts >= {start_ts_n} AND (ts + dur) <= {end_ts_n}
            AND name IN ({names_str}) 
            GROUP BY 1
        """
        df_n = self._common_api.tp_n.query(query_n).as_pandas_dataframe()
        avg_map = dict(zip(df_n['name'], df_n['avg_n']))

        # 3. 모든 인스턴스에 대해 지연 기여도(Delta) 계산
        candidates = []
        for _, row in df_all_s.iterrows():
            avg_val = avg_map.get(row['name'], 0) # Normal에 없으면 0ms (순수 신규 지연)
            delta = row['slow_ms'] - avg_val
            candidates.append({
                'id': int(row['id']), 'name': row['name'], 
                'ts': int(row['ts']), 'dur': int(row['dur']),
                'delta': delta, 'slow_ms': row['slow_ms']
            })
        
        # Delta가 큰 순서대로 정렬
        candidates.sort(key=lambda x: x['delta'], reverse=True)

        # 4. [핵심] 시간 범위 중첩 필터: 부모-자식-후손 관계 원천 차단
        worst_instances = []
        for cand in candidates:
            if len(worst_instances) >= limit: break
            
            is_redundant = False
            c_start, c_end = cand['ts'], cand['ts'] + cand['dur']
            
            for selected in worst_instances:
                s_start, s_end = selected['ts'], selected['ts'] + selected['dur']
                # 두 슬라이스의 시간이 겹치면 같은 계통(Stack)임
                if (c_start >= s_start and c_end <= s_end) or \
                   (s_start >= c_start and s_end <= c_end):
                    is_redundant = True
                    break
            
            if not is_redundant:
                worst_instances.append(cand)
        
        return worst_instances

    def _get_node_metrics_by_id(self, tp, utid, slice_id, start_ts=None, end_ts=None):
        """
        [수정] Self Time 계산 방식을 Running State 기반으로 변경하여 정확도 향상
        """
        query = f"SELECT ts, dur FROM slice WHERE id = {slice_id}"
        res = tp.query(query).as_pandas_dataframe()
        if res.empty: return None
        
        s_ts, s_dur = res.iloc[0]['ts'], res.iloc[0]['dur']
        a_start = max(s_ts, start_ts) if start_ts is not None else s_ts
        a_end = min(s_ts + s_dur, end_ts) if end_ts is not None else s_ts + s_dur
        
        # Thread State 정밀 분석
        state_query = f"""
            SELECT state, SUM(CASE 
                WHEN ts < {a_start} THEN ts + dur - {a_start}
                WHEN ts + dur > {a_end} THEN {a_end} - ts
                ELSE dur END) as clipped_dur_ns
            FROM thread_state WHERE utid = {utid} 
            AND ts + dur > {a_start} AND ts < {a_end} GROUP BY 1
        """
        st_res = tp.query(state_query).as_pandas_dataframe()
        
        # 실제 실행 시간 (Running)
        running_ms = st_res[st_res['state'].isin(['Running', 'R'])]['clipped_dur_ns'].sum() / 1e6
        # 대기 시간 (Wait/Runnable/Blocked)
        total_wait_ms = st_res[st_res['state'].isin(['R', 'D', 'DK'])]['clipped_dur_ns'].sum() / 1e6
        
        # [수정] Self Time은 이제 뺄셈이 아니라 실제 Running 상태를 기준으로 합니다.
        return {
            'dur': round((a_end - a_start) / 1e6, 2),
            'self': round(running_ms, 2), # 병렬 실행 시에도 모순이 없는 수치
            'wait': round(total_wait_ms, 2),
            'raw_ts': s_ts, 'raw_dur': s_dur
        }

    def _get_node_metrics_by_name(self, tp, utid, name, start_ts=None, end_ts=None):
        clean_name = name.replace("'", "''")
        query = f"SELECT id FROM slice WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid}) AND name = '{clean_name}' AND ts >= {start_ts} AND (ts + dur) <= {end_ts} ORDER BY dur DESC LIMIT 1"
        res = tp.query(query).as_pandas_dataframe()
        return self._get_node_metrics_by_id(tp, utid, res.iloc[0]['id'], start_ts, end_ts) if not res.empty else None

    def _get_structural_children(self, tp, parent_id):
        return tp.query(f"SELECT id, name, ts, dur FROM slice WHERE parent_id = {parent_id} ORDER BY dur DESC LIMIT 10").as_pandas_dataframe()

    def get_global_bounds(self, tp_type="slow"):
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        if tp is None: return None
        try:
            res = tp.query("SELECT start_ts, end_ts FROM trace_bounds").as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]): return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
            res = tp.query("SELECT MIN(ts), MAX(ts+dur) FROM slice").as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]): return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
        except: pass
        return None

    def get_thread_candidates(self, tp, upid, global_ts=None):
        if tp is None or upid is None: return None
        ts_f = f"AND ts >= {global_ts[0]} AND ts < {global_ts[1]}" if global_ts else ""
        query = f"SELECT t.utid, t.name AS thread_name, ((CASE WHEN t.name = p.name THEN 150 ELSE 0 END) + (CASE WHEN EXISTS (SELECT 1 FROM slice s JOIN thread_track tt ON s.track_id = tt.id WHERE tt.utid = t.utid {ts_f} AND (s.name LIKE 'Choreographer%' OR s.name LIKE 'doFrame%') LIMIT 1) THEN 250 ELSE 0 END) + COALESCE((SELECT SUM(dur)/1e6 FROM thread_state ts WHERE ts.utid = t.utid AND ts.state IN ('R', 'D', 'DK') {ts_f}), 0) * 0.05) AS total_score FROM thread t JOIN process p USING(upid) WHERE p.upid = {upid} ORDER BY total_score DESC;"
        return tp.query(query).as_pandas_dataframe()

    def check_thread_similarity(self, utid_n, utid_s):
        def get_set(tp, utid):
            df = tp.query(f"SELECT DISTINCT name FROM slice WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid}) LIMIT 100").as_pandas_dataframe()
            return set(df['name']) if not df.empty else set()
        sn, ss = get_set(self._common_api.tp_n, utid_n), get_set(self._common_api.tp_s, utid_s)
        return len(sn & ss) / len(sn | ss) if sn and ss else 0.0

    def _abort_investigation(self, reason, detail):
        self.output_callback(f"\n❌ [ANALYSIS ABORTED] {reason}\n   - {detail}", True)

    def get_clean_json_for_ai(self, data):
        if isinstance(data, list): return [self.get_clean_json_for_ai(i) for i in data]
        if isinstance(data, dict): return {k: self.get_clean_json_for_ai(v) for k, v in data.items() if not k.startswith("__internal")}
        return data