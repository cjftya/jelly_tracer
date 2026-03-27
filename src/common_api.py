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

    def release(self):
        self.tp_n.close()
        self.tp_s.close()
        self.tp_n = None
        self.tp_s = None

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
                    print(f"ℹ️ INFO: UPID apprehended via package_list (UID: {uid}).")
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
            print(f"ℹ️ INFO: UPID successfully traced via thread table mapping.")
            return int(res["upid"].iloc[0])

        return None