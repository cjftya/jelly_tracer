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
        except Exception as e:
            return None

    def parse(self, file_path):
        if not os.path.exists(file_path): return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)

            scan_type = raw_data.get("scan_type", None)
            
            # 🌟 로드된 raw_data를 그대로 넘겨서 파일 중복 오픈 방지
            if scan_type == "point":
                return self._parse_point_scan_logic(raw_data)
            elif scan_type == "insight":
                return self._parse_insight_scan_logic(raw_data)
            return None
        except Exception:
            return None
            
    def _parse_point_scan_logic(self, raw_data):
        # 🛡️ .get("key", {}) 패턴을 사용하여 중간 키가 없어도 에러 안 나게 방어
        metadata = raw_data.get("metadata", {})
        window = raw_data.get("target_window", {})
        intel = raw_data.get("forensic_intel", {})
        targeting = raw_data.get("targeting", {})
        guide = raw_data.get("compression_guide", {})

        return {
            "header": {
                "id": metadata.get("investigation_id"),
                "package": metadata.get("target_package"),
                "thread": metadata.get("target_thread"),
                "num_cpus": metadata.get("num_cpus", 8)
            },
            "window": {
                "start": window.get("start_ms", 0),
                "end": window.get("end_ms", 0),
                "margin": window.get("margin_ms", 50.0)
            },
            "intel": {
                "brief": intel.get("reasoning_brief", ""),
                "verdict": intel.get("verdict", "N/A"),
                "correlation_ids": targeting.get("correlation_ids", []),
                "confidence": targeting.get("confidence_score", 0.0)
            },
            "constraints": {
                "ignore_history": guide.get("ignore_history", []),
                "backtrack_count": targeting.get("backtrack_count", 0)
            }
        }

    def _parse_insight_scan(self, file_path):
        return None