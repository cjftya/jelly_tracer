from typing import Any, Dict, Optional


class BaseClient:
    def start_engine(self) -> None:
        pass

    def stop_engine(self) -> None:
        pass

    def set_api_key(self, api_key: Optional[str]) -> None:
        pass

    def get_model_name(self) -> str:
        return ""

    def get_options(self) -> Dict[str, Any]:
        return {}

    def request(
        self,
        context: Any,
        options: Optional[Dict[str, Any]] = None,
        chunk_callback=None,
    ) -> Dict[str, Any]:
        raise NotImplementedError
