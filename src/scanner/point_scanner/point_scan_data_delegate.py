import pandas as pd
import numpy as np
from common_api import CommonAPI

class PointScanDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.utid_n = None
        self.utid_s = None
        self.ts_n = None # Normal 트레이스 전체 시간 범위 [start, end]
        self.ts_s = None # Slow 트레이스 전체 시간 범위 [start, end]
        self.target_thread = None
        self.output_callback = output_callback

    def init(self, trace_normal, trace_slow, target_package):
        self._common_api = CommonAPI(trace_normal, trace_slow, target_package)

        # 초기화 시점에 각 트레이스의 전체 시간 경계를 구합니다.
        self.ts_n = self.get_global_bounds("normal")
        self.ts_s = self.get_global_bounds("slow")
        
        if not self.ts_n or not self.ts_s:
            self.output_callback("⚠️ [Warning] Failed to retrieve global trace bounds.")

    def identify_targets(self):
        self.output_callback("🔍 [Targeting] Identifying primary investigation targets...", True)

        # 1. Slow 트레이스에서 지연 임팩트가 가장 큰 범인(Culprit) 추출
        res_s = self.get_thread_candidates(self._common_api.tp_s, self._common_api.upid_s, self.ts_s)
        
        if res_s is None or res_s.empty:
            self.output_callback("🚨 [CRITICAL] No active threads found in SLOW trace.", True)
            return None, None, None

        target_row_s = res_s.iloc[0]
        self.target_thread = target_row_s['thread_name']
        self.utid_s = int(target_row_s['utid'])
        
        self.output_callback(f"🕵️‍♂️ [Suspect Identified] '{self.target_thread}' (Score: {target_row_s['total_score']:.1f})", True)

        # 2. Normal 트레이스에서 대조군 후보군 추출
        res_n = self.get_thread_candidates(self._common_api.tp_n, self._common_api.upid_n, self.ts_n)

        if res_n is None or res_n.empty:
            self.output_callback("🚨 [CRITICAL] Package data not found in NORMAL trace.", True)
            return None, None, None

        # 3. [Strict Match] 이름 기반 동일 스레드 매칭
        match_n = res_n[res_n['thread_name'] == self.target_thread]

        if match_n.empty:
            self._abort_investigation("Thread Name Mismatch", f"Target '{self.target_thread}' not found in Normal trace.")
            return None, None, None

        self.utid_n = int(match_n.iloc[0]['utid'])

        # 4. [Structural Check] 내부 슬라이스 유사도(유전자) 검사
        similarity = self.check_thread_similarity(self.utid_n, self.utid_s)
        
        if similarity > 0.7:
            status = "✅ [High Confidence]"
        elif similarity > 0.35:
            status = "⚠️ [Moderate Confidence]"
        else:
            self._abort_investigation("Structural Inconsistency", f"Similarity too low ({similarity:.1%}).")
            return None, None, None

        self.output_callback(f"{status} Baseline Matched. (Similarity: {similarity:.1%})", True)
        return self.utid_n, self.utid_s, self.target_thread

    def get_l1_delta_packages(self):
        if not self.utid_s or not self.utid_n:
            return "🚨 [Error] Target threads not identified. Run identify_targets() first."

        # 1. 지연 임팩트가 가장 큰 Worst 3 지점 탐색
        worst_roots = self._find_worst_slices(self.utid_n, self.utid_s)
        if not worst_roots:
            return "⚠️ [Notice] No significant regression found in the target thread."
        
        all_case_reports = []
        for i, root in enumerate(worst_roots):
            # 2. 시간 범위 확정 (없을 경우 전체에서 검색)
            ts_range = (root['ts'], root['ts_end']) if 'ts' in root else self._get_default_range(root['name'])
            
            tree_text = self._build_delta_tree_recursive(
                name=root['name'],
                ts_s=ts_range,
                depth=1
            )
            
            report = f"### [CASE {i+1}: {root['name']}]\n"
            report += f"- Total Impact Score: {root['impact']:.1f}\n"
            report += f"```text\n{tree_text}```"
            all_case_reports.append(report)

        return "\n\n".join(all_case_reports)

    def _build_delta_tree_recursive(self, name, ts_s, depth):
        if depth > 3: return ""

        # A. Slow 및 Normal 데이터 추출
        s_metrics = self._get_node_metrics(self._common_api.tp_s, self.utid_s, name, ts_s)
        n_metrics = self._get_node_metrics(self._common_api.tp_n, self.utid_n, name) # Normal은 전체에서 Baseline 검색

        if not s_metrics: return ""

        # B. 델타 및 태그 계산
        s_dur = s_metrics['dur']
        n_dur = n_metrics['dur'] if n_metrics else 0
        delta = s_dur - n_dur
        tag = self._get_impact_tag(delta, n_metrics is None, s_metrics['count'])
        
        # C. 텍스트 포맷팅
        indent = "  " * (depth - 1)
        prefix = "|-- " if depth > 1 else "- "
        n_dur_str = f"{n_dur:.1f}" if n_metrics else "N/A"
        n_state_str = n_metrics['state'] if n_metrics else "N/A"
        
        node_line = (f"{indent}{prefix}[L{depth}] {name} | "
                    f"{s_dur:.1f} ({n_dur_str}) | Δ{delta:+.1f} | "
                    f"Self:{s_metrics['self']:.1f} | Wait:{s_metrics['wait']:.1f} | "
                    f"{s_metrics['state']}({n_state_str}) | CPU:{s_metrics['cpu']}% | "
                    f"n:{s_metrics['count']} | {tag}\n")

        # D. 자식 노드 탐색 (Slow 기준)
        child_texts = ""
        if depth < 3:
            children = self._get_children(self._common_api.tp_s, self.utid_s, ts_s)
            for _, child in children.iterrows():
                child_texts += self._build_delta_tree_recursive(
                    child['name'], (child['ts'], child['ts'] + child['dur']), depth + 1
                )

        return node_line + child_texts

    def _get_node_metrics(self, tp, utid, name, ts_range=None):
        clean_name = name.replace("'", "''")
        time_filter = f"AND ts >= {ts_range[0]} AND ts <= {ts_range[1]}" if ts_range else ""
        
        query = f"""
            SELECT ts, dur, (SELECT SUM(dur) FROM slice WHERE parent_id = s.id) as child_dur
            FROM slice s WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid})
            AND name = '{clean_name}' {time_filter} ORDER BY dur DESC LIMIT 1
        """
        res = tp.query(query).as_pandas_dataframe()
        if res.empty: return None

        ts, dur, c_dur = res.iloc[0]['ts'], res.iloc[0]['dur'] / 1e6, (res.iloc[0]['child_dur'] or 0) / 1e6
        
        # Thread State (Wait/CPU)
        state_query = f"""
            SELECT state, SUM(dur)/1e6 as state_dur
            FROM thread_state WHERE utid = {utid} AND ts >= {ts} AND ts <= {ts + (dur*1e6)}
            GROUP BY 1 ORDER BY 2 DESC
        """
        st_res = tp.query(state_query).as_pandas_dataframe()
        wait_time = st_res[st_res['state'] == 'R']['state_dur'].sum()
        run_time = st_res[st_res['state'] == 'Running']['state_dur'].sum()
        dominant_state = st_res.iloc[0]['state'][0].upper() if not st_res.empty else "U"
        
        # Count (n)
        count_query = f"SELECT COUNT(*) as cnt FROM slice WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid}) AND name = '{clean_name}' {time_filter}"
        count = tp.query(count_query).as_pandas_dataframe().iloc[0]['cnt']

        return {
            'dur': dur, 'self': max(0, dur - c_dur), 'wait': wait_time,
            'state': dominant_state, 'cpu': int((run_time / dur * 100)) if dur > 0 else 0,
            'count': count
        }

    def _find_worst_slices(self, utid_n, utid_s, limit=3):
        self.output_callback("🛰️ [Initial Scan] Searching for top 3 regression pivots...", True)

        # 1. Slow 트레이스에서 실행 시간이 긴 후보들 추출
        query_s = f"""
            SELECT name, SUM(dur)/1e6 as slow_ms, MAX(ts) as ts, MAX(ts + dur) as ts_end
            FROM slice 
            WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid_s})
            AND dur > 0 GROUP BY 1 ORDER BY 2 DESC LIMIT 30
        """
        df_s = self._common_api.tp_s.query(query_s).as_pandas_dataframe()
        if df_s.empty: return []

        # 2. SQL IN 절을 위한 이름 리스트 포매팅 (작은따옴표 이스케이프 포함)
        names_list = df_s['name'].tolist()
        formatted_names = ", ".join(["'" + n.replace("'", "''") + "'" for n in names_list])
        name_filter = f"name IN ({formatted_names})" if names_list else "1=0"
        
        # 3. Normal 트레이스에서 동일한 이름의 슬라이스 시간 조회
        query_n = f"""
            SELECT name, SUM(dur)/1e6 as normal_ms 
            FROM slice 
            WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid_n}) 
            AND {name_filter} 
            GROUP BY 1
        """
        df_n = self._common_api.tp_n.query(query_n).as_pandas_dataframe()

        # 4. 데이터 병합 및 타입 안정성 확보 (FutureWarning 방지)
        df_merged = pd.merge(df_s, df_n, on='name', how='left')
        # Pandas 최신 버전 대응: 다운캐스팅 경고 방지
        df_merged = df_merged.infer_objects(copy=False)
        df_merged = df_merged.fillna(0)

        # 5. 임팩트 스코어 계산 (지연 시간 * 지연 비율)
        df_merged['delta'] = df_merged['slow_ms'] - df_merged['normal_ms']
        df_merged['ratio'] = df_merged['slow_ms'] / (df_merged['normal_ms'] + 0.1)
        df_merged['impact_score'] = df_merged['delta'] * df_merged['ratio']
        
        # 점수가 높은 순으로 정렬
        df_merged = df_merged.sort_values(by='impact_score', ascending=False)

        # 6. 최종 Worst 3 선정 (지연이 발생한 경우만)
        final_worst_list = []
        for _, row in df_merged.iterrows():
            if len(final_worst_list) >= limit: break
            
            # 최소 실행 시간 1ms 이상이고, '정상'보다 조금이라도 느려진 것만 포함
            if row['slow_ms'] >= 1.0 and row['impact_score'] > 0:
                final_worst_list.append({
                    'name': row['name'], 
                    'impact': row['impact_score'],
                    'ts': int(row['ts']), 
                    'ts_end': int(row['ts_end']),
                    'slow_ms': row['slow_ms'], 
                    'delta': row['delta']
                })
                self.output_callback(f"🚩 [Pivot {len(final_worst_list)}] '{row['name']}' (Impact: {row['impact_score']:.1f})", True)
        
        return final_worst_list

    def _get_children(self, tp, utid, ts_range):
        # 정확한 ts 매칭보다는 부모-자식 관계(parent_id)나 계층 범위를 활용
        query = f"""
            SELECT name, ts, dur FROM slice 
            WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid})
            AND ts >= {ts_range[0]} AND (ts + dur) <= {ts_range[1]}
            AND depth = (SELECT depth + 1 FROM slice 
                        WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid})
                        AND ts >= {ts_range[0]} AND ts <= {ts_range[0]} + 1000 LIMIT 1)
            ORDER BY dur DESC LIMIT 5
        """
        return tp.query(query).as_pandas_dataframe()

    def _get_default_range(self, name):
        res = self.get_slice_bounds("slow", self.utid_s, name)
        return tuple(res) if res else (0, 0)

    def _get_impact_tag(self, delta, is_new, count):
        if is_new: return "[NEW_ENTRY] 🔥"
        if delta > 50: return "[CRITICAL] 💥"
        if delta > 10: return "[REGRESSION]"
        if count > 10: return "[LOOP_DETECTED]"
        return "[NORMAL]"

    def get_thread_candidates(self, tp, upid, global_ts=None):
        if tp is None or upid is None: return None
        ts_filter = f"AND ts >= {global_ts[0]} AND ts < {global_ts[1]}" if global_ts else ""
        query = f"""
            SELECT t.utid, t.name AS thread_name, (
                (CASE WHEN t.name = p.name THEN 150 ELSE 0 END) +
                (CASE WHEN EXISTS (SELECT 1 FROM slice s JOIN thread_track tt ON s.track_id = tt.id WHERE tt.utid = t.utid {ts_filter} AND (s.name LIKE 'Choreographer%' OR s.name LIKE 'doFrame%') LIMIT 1) THEN 250 ELSE 0 END) +
                COALESCE((SELECT SUM(dur)/1e6 FROM thread_state ts WHERE ts.utid = t.utid AND ts.state IN ('R', 'D', 'DK') {ts_filter}), 0) * 0.05
            ) AS total_score FROM thread t JOIN process p USING(upid) WHERE p.upid = {upid} ORDER BY total_score DESC;
        """
        return tp.query(query).as_pandas_dataframe()

    def check_thread_similarity(self, utid_n, utid_s):
        def get_slice_set(tp, utid):
            query = f"SELECT DISTINCT name FROM slice WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid}) LIMIT 100"
            df = tp.query(query).as_pandas_dataframe()
            return set(df['name']) if not df.empty else set()
        set_n, set_s = get_slice_set(self._common_api.tp_n, utid_n), get_slice_set(self._common_api.tp_s, utid_s)
        if not set_n or not set_s: return 0.0
        return len(set_n & set_s) / len(set_n | set_s)

    def _abort_investigation(self, reason, detail):
        self.output_callback(f"\n❌ [ANALYSIS ABORTED] {reason}\n   - {detail}\n" + "-"*50 + "\n💡 재추출 가이드: 시나리오 일치 확인 및 Normal 실행 데이터 확보 필요.\n" + "-"*50, True)

    def get_global_bounds(self, tp_type="slow"):
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        if tp is None: return None
        
        try:
            # 1. 표준 trace_bounds 테이블 확인
            res = tp.query("SELECT start_ts, end_ts FROM trace_bounds").as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
                
            # 2. Fallback: slice 테이블에서 전체 범위 계산
            res = tp.query("SELECT MIN(ts), MAX(ts+dur) FROM slice").as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
        except Exception as e:
            self.output_callback(f"⚠️ [Bounds Error] {tp_type}: {str(e)}")
        return None

    def get_slice_bounds(self, tp_type, utid, name, scope_ts=None):
        tp = self._common_api.tp_s if tp_type == "slow" else self._common_api.tp_n
        if tp is None: return None

        # 싱글 쿼트 대응 및 앞뒤 공백 제거
        clean_name = name.strip().replace("'", "''")
        
        # [개선] 단일 트랙이 아닌, 해당 utid와 관련된 모든 thread_track을 뒤짐
        # [개선] 정확히 일치(=)뿐만 아니라 유연한 매칭(LIKE) 옵션 고려 가능 (여기선 = 유지)
        query = f"""
            SELECT ts, (ts + dur) as end_ts 
            FROM slice 
            WHERE track_id IN (SELECT id FROM thread_track WHERE utid = {utid}) 
            AND name = '{clean_name}'
        """
        
        if scope_ts:
            query += f" AND ts >= {scope_ts[0]} AND ts <= {scope_ts[1]}"
        
        # 지연 분석이므로 가장 긴 놈을 우선
        query += " ORDER BY dur DESC LIMIT 1"
        
        try:
            res = tp.query(query).as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]
            
            # [보험] 만약 못 찾았다면, 이름 앞뒤에 공백이 있는지 LIKE로 한 번 더 시도
            query_retry = query.replace(f"name = '{clean_name}'", f"name LIKE '%{clean_name}%'")
            res = tp.query(query_retry).as_pandas_dataframe()
            if not res.empty and pd.notna(res.iloc[0, 0]):
                return [int(res.iloc[0, 0]), int(res.iloc[0, 1])]

        except Exception as e:
            self.output_callback(f"⚠️ [Query Error] {str(e)}")
            
        return None

    def get_sync_bounds(self, tp_type, reference_ts):
        duration = reference_ts[1] - reference_ts[0]
        bounds = self.get_global_bounds(tp_type)
        return [bounds[0], bounds[0] + duration] if bounds else None

    def check_thread_scheduling(self, thread_name="auto"):
        return self._common_api.check_thread_scheduling(thread_name)

    def profile_thread_functions(self, thread_name="auto"):
        return self._common_api.profile_thread_functions(thread_name)