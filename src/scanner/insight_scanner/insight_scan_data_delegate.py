import pandas as pd

class InsightScanDataDelegate:
    def __init__(self, output_callback):
        self._common_api = None
        self.output_callback = output_callback
        self.package = None

    def init(self, common_api, target_package):
        self._common_api = common_api
        self.package = target_package

    def fetch_deep_dive_package(self, collected_data):
        target = collected_data.get("target_data", {})
        try:
            target_id = int(target.get("target_id", 0))
            start_ns = int(target.get("start_ts_ns", 0))
            duration_ns = int(target.get("duration_ns", 0))
            utid = int(target.get("utid", 0))
        except (ValueError, TypeError):
            self.output_callback("🚨 [Error] Invalid numeric data in master_data.", True)
            return None

        end_ns = start_ns + duration_ns
        self.output_callback(f"🧬 [Deep-Scan] Extracting Core Evidence (Target ID: {target_id}, UTID: {utid})", True)

        tp_s = self._common_api.tp_s
        if tp_s is None:
            self.output_callback("🚨 [Error] Trace Processor is not initialized.", True)
            return None

        return {
            "virtual_stack_trace": self._get_vertical_stack(tp_s, utid, start_ns, end_ns),
            "binder_transactions": self._get_binder_payload(tp_s, utid, start_ns, end_ns),
            "monitor_locks": self._get_lock_contention(tp_s, utid, start_ns, end_ns)
        }

    def _get_vertical_stack(self, tp, utid, start_ns, end_ns):
        query = f"""
            SELECT 
                slice.depth as depth_level, 
                COALESCE(slice.name, '<unnamed_slice>') as method_fullname, 
                round(slice.dur / 1e6, 2) as duration_milliseconds
            FROM slice
            JOIN thread_track ON slice.track_id = thread_track.id
            WHERE thread_track.utid = {utid}
            AND slice.ts < {end_ns} AND (slice.ts + slice.dur) > {start_ns}
            ORDER BY slice.ts ASC, slice.depth ASC
            LIMIT 25
        """
        return tp.query(query).as_pandas_dataframe().to_dict(orient='records')

    def _get_binder_payload(self, tp, utid, start_ns, end_ns):
        query = f"""
            SELECT 
                COALESCE((SELECT p.name FROM process p JOIN thread t USING(upid) WHERE t.utid = {utid}), '{self.package}') as caller_process_name,
                COALESCE((SELECT name FROM thread WHERE utid = {utid}), '<unknown_thread>') as caller_thread_name,
                COALESCE(EXTRACT_ARG(slice.arg_set_id, 'destination_package'), '<unknown_destination>') as target_process_name,
                COALESCE(slice.name, 'binder_call') as method_name, 
                round(slice.dur / 1e6, 2) as wait_milliseconds
            FROM slice
            JOIN thread_track ON slice.track_id = thread_track.id
            WHERE thread_track.utid = {utid}
            AND (slice.name LIKE 'binder %' OR slice.name LIKE 'reply %')
            AND slice.ts < {end_ns} AND (slice.ts + slice.dur) > {start_ns}
            ORDER BY slice.dur DESC
            LIMIT 20
        """
        return tp.query(query).as_pandas_dataframe().to_dict(orient='records')

    def _get_lock_contention(self, tp, utid, start_ns, end_ns):
        query = f"""
            SELECT 
                COALESCE(slice.name, 'monitor_lock') as lock_name, 
                round(slice.dur / 1e6, 2) as wait_milliseconds,
                COALESCE(EXTRACT_ARG(slice.arg_set_id, 'owner_thread_name'), '<no_holder_info>') as lock_holder_thread_name
            FROM slice
            JOIN thread_track ON slice.track_id = thread_track.id
            WHERE thread_track.utid = {utid}
            AND (slice.name LIKE '%contention%' OR slice.name LIKE '%Lock%')
            AND slice.ts < {end_ns} AND (slice.ts + slice.dur) > {start_ns}
            ORDER BY slice.dur DESC
            LIMIT 10
        """
        return tp.query(query).as_pandas_dataframe().to_dict(orient='records')