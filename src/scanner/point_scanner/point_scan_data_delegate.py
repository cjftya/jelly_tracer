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

    def init(self, trace_normal, trace_slow, target_package):
        """두 트레이스 파일을 로드하고 분석을 위한 기초 시간 범위를 설정합니다."""
        self._common_api = CommonAPI(trace_normal, trace_slow, target_package)
        
        # 전체 트레이스의 시작과 끝을 구해야 나중에 스레드 점수를 매길 때 범위를 한정할 수 있습니다.
        self.ts_n = self.get_global_bounds("normal")
        self.ts_s = self.get_global_bounds("slow")
        
        if not self.ts_n or not self.ts_s:
            self.output_callback("⚠️ [Warning] Failed to retrieve global trace bounds.", True)

    def get_common_milestones(self):
        core_candidates = ['bindApplication', 'activityStart', 'activityResume']
        def fetch_milestones(mode):
            # [수정] API 구조에 따라 안전하게 tp와 upid를 가져옵니다.
            try:
                # 메서드 형태인 경우
                tp = self._common_api.get_trace_processor(mode)
                upid = self._common_api.get_upid(mode)
            except AttributeError:
                # 속성 형태인 경우 (주신 코드 기준)
                tp = self._common_api.tp_n if mode == "normal" else self._common_api.tp_s
                upid = self._common_api.upid_n if mode == "normal" else self._common_api.upid_s
            
            if tp is None or upid is None:
                return {}

            # 2. 코어 마일스톤 추출 (프로세스 내 모든 스레드 대상)
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
            
            # 3. '화면 변화 없음' 지점 찾기 (Visual Idle)
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
                    "ts_n": ms_n[name],
                    "ts_s": ms_s[name],
                    "delta_ms": round(delta_ms, 2),  # [핵심] 누적 지연 시간
                    "elapsed_ms_s": round(elapsed_s, 2) # Slow 기준 진행 시간 (UI 표시용)
                })

        if self.output_callback:
            self.output_callback("\n🔍 [Recommended Start-End Points]", True)
            self.output_callback("=" * 45, True)
            
            prev_delta = 0
            for m in final_milestones:
                curr_delta = m['delta_ms']
                step_delay = curr_delta - prev_delta  # 이번 구간에서 늘어난 시간
                
                # 30ms 이상 늘어난 구간은 바로 눈에 띄게 표시
                if step_delay >= 30:
                    mark = "🔴 [Focus]"
                elif step_delay > 0:
                    mark = f"(+{step_delay:>5.1f}ms ↑)"
                else:
                    mark = ""

                msg = f"📍 {m['name']:<18} : {curr_delta:>7.1f}ms {mark}"
                self.output_callback(msg, True)
                
                prev_delta = curr_delta

            self.output_callback("=" * 45, True)
        return final_milestones

    def identify_targets(self):
        """
        수사 대상이 될 메인 스레드를 식별합니다. 
        이름 매칭뿐만 아니라 실행 점수(Total Score)를 계산하여 가장 의심스러운 놈을 잡습니다.
        """
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
        """
        핵심 엔진: 3개의 최악 사례(Worst Cases)를 추출하여 JSON 트리로 변환합니다.
        R1 모델이 이 데이터를 읽고 범인을 지목하게 됩니다.
        """
        if not self.utid_s or not self.utid_n:
            return {"error": "Target threads not identified."}

        self.output_callback("🚀 [JSON Engine] Starting high-precision data condensation and tree generation...", True)

        # 1. 지연이 가장 심한 3개의 핵심 슬라이스(Root)를 찾습니다.
        if not self.ts_s:
            return {"error": "Trace bounds not available."}

        start_ts_n, end_ts_n = start_m['ts_n'], end_m['ts_n']
        start_ts_s, end_ts_s = start_m['ts_s'], end_m['ts_s']
            
        worst_roots = self._find_worst_slices(self.utid_n, self.utid_s, start_ts_n, end_ts_n, start_ts_s, end_ts_s)
        if not worst_roots:
            return {"worst_cases": []}

        worst_cases_data = []
        for i, root in enumerate(worst_roots):
            # 2. 각 Root부터 자식 노드들을 Depth 3까지 재귀적으로 파고듭니다 (Top 3 + Others 전략).
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
                "issue": f"Performance regression in {root['name']}",
                "total_duration": round(root['slow_ms'], 1),
                "tree": tree
            })

        return {"worst_cases": worst_cases_data}

    def _build_json_tree_recursive(self, slice_id, name, parent_delta, depth,
                                    start_ts_n, end_ts_n, start_ts_s, end_ts_s):
        """
        재귀적으로 트리를 구축하며, 계층별로 중요한 노드만 남기고 나머지는 합칩니다 (데이터 응축).
        """
        if depth > 3: return None  # LLM의 집중력을 위해 Depth 3까지만 분석합니다.

        # 현재 노드의 상세 지표(지연 시간, Self Time, Wait Time 등)를 가져옵니다.
        s_metrics = self._get_node_metrics_by_id(self._common_api.tp_s, self.utid_s, slice_id, 
                                             start_ts=start_ts_s, end_ts=end_ts_s)
        # Normal 대조군에서는 가장 긴 인스턴스를 Baseline으로 가져옵니다.
        n_metrics = self._get_node_metrics_by_name(self._common_api.tp_n, self.utid_n, name,
                                               start_ts=start_ts_n, end_ts=end_ts_n)

        if not s_metrics: return None

        s_dur = s_metrics['dur']
        n_dur = n_metrics['dur'] if n_metrics else 0
        delta = s_dur - n_dur
        
        # 부모 노드의 지연 중 이 노드가 차지하는 비중(Impact Ratio) 계산
        impact_ratio = round(max(0, delta / parent_delta), 2) if parent_delta > 0 else 0.0
        # 지연 시간과 증가율을 결합한 영향력 점수(Impact Score)
        impact_score = round(max(0, delta * (s_dur / (n_dur + 0.1))), 1)

        node_data = {
            "name": name,
            "delta_time": round(delta, 1),
            "self_time": round(s_metrics['self'], 1),
            "wait_time": round(s_metrics['wait'], 1),
            "impact_ratio": impact_ratio,
            "children": [],
            "__internal_id": int(slice_id),
            "__internal_ts": s_metrics['raw_ts'],
            "__internal_dur": s_metrics['raw_dur'],
            "__internal_utid": int(self.utid_s)
        }

        # 자식 노드들을 분석하여 상위 3개만 유지하고 나머지는 'others'로 합산합니다.
        if depth < 3:
            children_df = self._get_structural_children(self._common_api.tp_s, slice_id)
            if not children_df.empty:
                child_candidates = []
                for _, child in children_df.iterrows():
                    c_n_metrics = self._get_node_metrics_by_name(
                        self._common_api.tp_n, self.utid_n, child['name'],
                        start_ts=start_ts_n, end_ts=end_ts_n
                    )
                    c_n_dur = c_n_metrics['dur'] if c_n_metrics else 0
                    c_delta = (child['dur'] / 1e6) - c_n_dur
                    
                    child_candidates.append({
                        "id": int(child['id']),
                        "name": child['name'],
                        "delta": c_delta
                    })

                # 지연 시간(delta)이 큰 순서대로 정렬
                child_candidates.sort(key=lambda x: x['delta'], reverse=True)
                top_3 = child_candidates[:3]
                others = child_candidates[3:]

                # 상위 3개 노드는 다시 재귀 호출하여 하위 트리 구성
                for c in top_3:
                    child_node = self._build_json_tree_recursive(
                        c['id'], c['name'], delta, depth + 1,
                        start_ts_n, end_ts_n, start_ts_s, end_ts_s 
                    )
                    if child_node:
                        node_data["children"].append(child_node)

                # 나머지 마이너 노드들은 'others' 노드로 뭉쳐서 보여줍니다 (토큰 절약 및 노이즈 제거).
                if others:
                    others_delta = sum(o['delta'] for o in others)
                    node_data["children"].append({
                        "name": "others",
                        "delta_time": round(others_delta, 1),
                        "impact_score": 0,
                        "self_time": round(others_delta, 1),
                        "wait_time": 0,
                        # 여기서도 max(0, ...) 적용
                        "impact_ratio": round(max(0, others_delta / delta), 2) if delta > 0 else 0
                    })
        return node_data

    def _find_worst_slices(self, utid_n, utid_s, start_ts_n, end_ts_n, start_ts_s, end_ts_s, limit=3):
        """전체 트레이스에서 지연 임팩트가 가장 큰 3개의 '단일 최악 인스턴스'를 찾습니다."""
        self.output_callback("🛰️ [Initial Scan] Searching for the single worst instances of regressions...", True)
        
        # 1. Slow 트레이스 쿼리에 시간 범위(ts) 필터 추가
        query_s = f"""
            SELECT 
                name, 
                SUM(dur)/1e6 as total_slow_ms, 
                AVG(dur)/1e6 as avg_slow_ms
            FROM slice 
            WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid_s})
            AND ts >= {start_ts_s} AND (ts + dur) <= {end_ts_s}
            GROUP BY 1 
            ORDER BY 2 DESC 
            LIMIT 20
        """
        df_s = self._common_api.tp_s.query(query_s).as_pandas_dataframe()
        if df_s.empty: return []

        # 2. Normal 트레이스에서 해당 후보들의 평균(AVG) 실행 시간을 가져옵니다 (Baseline).
        # SQL 문법 에러 방지를 위해 문자열 조립 시 이스케이프 처리를 합니다.
        names_str = ", ".join(["'" + n.replace("'", "''") + "'" for n in df_s['name']])
        query_n = f"""
            SELECT name, AVG(dur)/1e6 as avg_normal_ms 
            FROM slice 
            WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid_n}) 
            AND ts >= {start_ts_n} AND (ts + dur) <= {end_ts_n}
            AND name IN ({names_str}) 
            GROUP BY 1
        """
        df_n = self._common_api.tp_n.query(query_n).as_pandas_dataframe()
        
        # Merge 수행 (df_s에 avg_slow_ms가 있으므로 df_merged에도 포함됩니다)
        df_merged = pd.merge(df_s, df_n, on='name', how='left').fillna(0)
        df_merged = df_merged.infer_objects(copy=False)
        
        # 수식은 (총 실행 시간) - (정상일 때 걸렸어야 할 시간)을 구하여 '진짜 지연된 총량'을 찾아냅니다.
        df_merged['impact'] = (df_merged['total_slow_ms'] - (df_merged['avg_normal_ms'] * (df_merged['total_slow_ms'] / (df_merged['avg_slow_ms'] + 0.1))))
        top_names = df_merged.sort_values('impact', ascending=False).head(limit)['name'].tolist()

        worst_instances = []
        for name in top_names:
            clean_name = name.replace("'", "''")
            # 각 후보 이름 중 '가장 길게 실행된 단일 시점(Worst Instance)'의 ID와 시간을 가져옵니다.
            inst_query = f"""
                SELECT id, name, ts, (ts+dur) as ts_end, dur/1e6 as slow_ms
                FROM slice WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid_s})
                AND name = '{clean_name}' ORDER BY dur DESC LIMIT 1
            """
            res = self._common_api.tp_s.query(inst_query).as_pandas_dataframe()
            if not res.empty:
                row = res.iloc[0]
                n_match = df_n[df_n['name'] == name]
                avg_n = n_match['avg_normal_ms'].iloc[0] if not n_match.empty else 0
                
                worst_instances.append({
                    'id': int(row['id']), 'name': row['name'], 'ts': int(row['ts']), 
                    'ts_end': int(row['ts_end']), 'slow_ms': row['slow_ms'], 
                    'delta': row['slow_ms'] - avg_n
                })
        return worst_instances

    def _get_node_metrics_by_id(self, tp, utid, slice_id, start_ts=None, end_ts=None):
        # 1. 슬라이스 기본 정보 및 자식 실행 시간 합계 추출
        query = f"""
            SELECT ts, dur, 
            (SELECT SUM(dur) FROM slice WHERE parent_id = {slice_id}) as child_dur 
            FROM slice WHERE id = {slice_id}
        """
        res = tp.query(query).as_pandas_dataframe()
        if res.empty: 
            return {'dur': 0, 'self': 0, 'wait': 0, 'raw_ts': 0, 'raw_dur': 0} # 기본값 추가
        
        row = res.iloc[0]
        s_ts = row['ts']      # 슬라이스 시작 시간 (ns)
        s_dur = row['dur']    # 슬라이스 실행 시간 (ns)
        c_dur_ns = row['child_dur'] or 0 # 자식들의 실행 시간 합계 (ns)
        
        # 2. 분석할 실제 유효 범위(Actual Range) 결정
        # 사용자가 선택한 마일스톤 구간과 현재 슬라이스 시간의 교집합을 구합니다.
        analysis_start = max(s_ts, start_ts) if start_ts is not None else s_ts
        analysis_end = min(s_ts + s_dur, end_ts) if end_ts is not None else s_ts + s_dur
        analysis_dur_ns = analysis_end - analysis_start

        # 구간이 겹치지 않으면 0 반환
        if analysis_dur_ns <= 0:
            return {'dur': 0, 'self': 0, 'wait': 0, 'raw_ts': 0, 'raw_dur': 0} # 기본값 추가

        # 3. Thread State 정밀 쿼리 (Clipping 로직 적용)
        # CASE WHEN을 사용하여 마일스톤 경계선에 걸친 스레드 상태의 길이를 나노초 단위로 정확히 자릅니다.
        state_query = f"""
            SELECT 
                state, 
                SUM(CASE 
                    WHEN ts < {analysis_start} THEN ts + dur - {analysis_start}
                    WHEN ts + dur > {analysis_end} THEN {analysis_end} - ts
                    ELSE dur 
                END) as clipped_dur_ns
            FROM thread_state 
            WHERE utid = {utid} 
            AND ts + dur > {analysis_start} 
            AND ts < {analysis_end} 
            GROUP BY 1
        """
        st_res = tp.query(state_query).as_pandas_dataframe()
        
        # 4. 메트릭 산출 (단위: ms)
        # Running: 실제 CPU 점유 시간 (R 또는 Running)
        # Runnable/Sleep: 대기 시간 (R, D, DK 등)
        # thread_state 테이블에서 'Running' 혹은 'R'로 표시되는 실제 실행 시간 추출
        running_time_ms = st_res[st_res['state'].isin(['Running', 'R'])]['clipped_dur_ns'].sum() / 1e6
        
        # 대기 상태들 합산 (Runnable='R', Blocked='D', Disk='DK')
        wait_states = ['R', 'D', 'DK']
        total_wait_ns = st_res[st_res['state'].isin(wait_states)]['clipped_dur_ns'].sum()
        
        # 최종 반환 값 정리
        full_dur_ms = analysis_dur_ns / 1e6
        # self_time: 전체 구간 길이에서 자식 노드들의 길이를 뺀 순수 본인 로직 실행 시간
        self_time_ms = max(0, full_dur_ms - (c_dur_ns / 1e6))
        # wait_time: 전체 대기 상태 합계에서 Running(실제 실행)을 제외한 순수 대기 시간
        wait_time_ms = max(0, (total_wait_ns / 1e6) - running_time_ms)

        return {
            'dur': round(full_dur_ms, 2),
            'self': round(self_time_ms, 2),
            'wait': round(wait_time_ms, 2),
            'raw_ts': s_ts,
            'raw_dur': s_dur
        }

    def _get_node_metrics_by_name(self, tp, utid, name, start_ts=None, end_ts=None): # [수정] 인자 추가
        """이름을 기준으로 해당 스레드에서 가장 길게 실행된 Baseline 데이터를 가져옵니다."""
        clean_name = name.replace("'", "''")
        query = f"""
            SELECT id FROM slice 
            WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid}) 
            AND name = '{clean_name}' 
            AND ts >= {start_ts} AND (ts + dur) <= {end_ts} 
            ORDER BY dur DESC LIMIT 1
        """
        res = tp.query(query).as_pandas_dataframe()
        if res.empty: return None
        # [수정] id 기반 함수를 호출할 때 구간 정보를 그대로 전달합니다.
        return self._get_node_metrics_by_id(tp, utid, res.iloc[0]['id'], start_ts=start_ts, end_ts=end_ts)

    def _get_structural_children(self, tp, parent_id):
        """parent_id를 이용하여 구조적으로 완벽하게 연결된 직계 자식 노드들을 추출합니다."""
        return tp.query(f"SELECT id, name, ts, dur FROM slice WHERE parent_id = {parent_id} ORDER BY dur DESC LIMIT 10").as_pandas_dataframe()

    def get_global_bounds(self, tp_type="slow"):
        """트레이스 파일의 전체 시간 범위를 추출합니다."""
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        if tp is None: return None
        try:
            res = tp.query("SELECT start_ts, end_ts FROM trace_bounds").as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
            # trace_bounds 테이블이 비어있을 경우 slice 테이블에서 최소/최대 ts를 직접 계산합니다.
            res = tp.query("SELECT MIN(ts), MAX(ts+dur) FROM slice").as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
        except Exception as e:
            self.output_callback(f"⚠️ [Bounds Error] {tp_type}: {str(e)}", True)
        return None

    def get_thread_candidates(self, tp, upid, global_ts=None):
        """패키지 내 스레드들을 점수화하여 주요 분석 대상 후보를 리스팅합니다."""
        if tp is None or upid is None: return None
        ts_filter = f"AND ts >= {global_ts[0]} AND ts < {global_ts[1]}" if global_ts else ""
        # 메인 스레드 여부, Choreographer 호출 여부, 스케줄링 지연 시간 등을 종합하여 점수를 매깁니다.
        query = f"""
            SELECT t.utid, t.name AS thread_name, (
                (CASE WHEN t.name = p.name THEN 150 ELSE 0 END) +
                (CASE WHEN EXISTS (SELECT 1 FROM slice s JOIN thread_track tt ON s.track_id = tt.id WHERE tt.utid = t.utid {ts_filter} AND (s.name LIKE 'Choreographer%' OR s.name LIKE 'doFrame%') LIMIT 1) THEN 250 ELSE 0 END) +
                COALESCE((SELECT SUM(dur)/1e6 FROM thread_state ts WHERE ts.utid = t.utid AND ts.state IN ('R', 'D', 'DK') {ts_filter}), 0) * 0.05
            ) AS total_score FROM thread t JOIN process p USING(upid) WHERE p.upid = {upid} ORDER BY total_score DESC;
        """
        return tp.query(query).as_pandas_dataframe()

    def check_thread_similarity(self, utid_n, utid_s):
        """두 스레드 간에 실행되는 슬라이스 이름들이 얼마나 겹치는지 체크하여 대조 가능성을 판단합니다."""
        def get_slice_set(tp, utid):
            query = f"SELECT DISTINCT name FROM slice WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid}) LIMIT 100"
            df = tp.query(query).as_pandas_dataframe()
            return set(df['name']) if not df.empty else set()
        set_n, set_s = get_slice_set(self._common_api.tp_n, utid_n), get_slice_set(self._common_api.tp_s, utid_s)
        if not set_n or not set_s: return 0.0
        # Jaccard 유사도 계산
        return len(set_n & set_s) / len(set_n | set_s)

    def _abort_investigation(self, reason, detail):
        self.output_callback(f"\n❌ [ANALYSIS ABORTED] {reason}\n   - {detail}", True)

    def get_clean_json_for_ai(self, data):  # 1. 여기에 self 추가
        if isinstance(data, list):
            # 2. 재귀 호출 시에도 self. 을 붙여줘야 합니다.
            return [self.get_clean_json_for_ai(item) for item in data]
        elif isinstance(data, dict):
            return {
                k: self.get_clean_json_for_ai(v)  # 3. 여기도 self. 추가
                for k, v in data.items() 
                if not k.startswith("__internal")
            }
        return data