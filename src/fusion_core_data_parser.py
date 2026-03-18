import json
import os

class FusionCoreDataParser:
    def __init__(self):
        pass

    def get_scan_type(self, file_path):
        if not os.path.exists(file_path):
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
            return raw_data.get("scan_type", None)
        except Exception:
            return None

    def parse(self, file_path):
        if not os.path.exists(file_path): return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)

            scan_type = raw_data.get("scan_type", None)
            
            if scan_type == "point":
                return self._parse_point_scan_logic(raw_data)
            elif scan_type == "insight":
                return None
            return None
        except Exception:
            return None
            
    def _parse_point_scan_logic(self, raw_data):
        metadata = raw_data.get("metadata", {})
        window = raw_data.get("target_window", {})
        intel = raw_data.get("forensic_intel", {})
        targeting = raw_data.get("targeting", {})
        guide = raw_data.get("compression_guide", {})
        archives = raw_data.get("raw_archives", {})

        return {
            "header": {
                "id": metadata.get("investigation_id"),
                "package": metadata.get("target_package"),
                "thread": metadata.get("target_thread"),
                "num_cpus": metadata.get("num_cpus", 8)
            },
            "window": {
                # 나노초(ns) 단위 정밀도 유지
                "start": window.get("start_ns", 0),
                "end": window.get("end_ns", 0),
                "margin": window.get("margin_ms", 50.0)
            },
            "intel": {
                "brief": intel.get("reasoning_brief", ""),
                "verdict": intel.get("verdict", "N/A"),
                "owner": intel.get("owner", "N/A"),
                "cause": intel.get("cause_korean", "N/A"),
                "action_items": intel.get("action_items", "N/A"),
                "confidence": targeting.get("confidence_score", 0.0),
                "pivot_candidates": targeting.get("pivot_candidates", [])
            },
            "constraints": {
                "ignore_history": guide.get("ignore_history", []),
                "backtrack_count": targeting.get("backtrack_count", 0),
                "app_pct": guide.get("reference_delta", {}).get("app_pct", "0"),
                "sys_pct": guide.get("reference_delta", {}).get("sys_pct", "0"),
                "investigated_depth": guide.get("investigated_depth", 0)
            },
            "thought_archives": archives.get("thought_archive", [])
        }