from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class BaseClient(ABC):
 
    @abstractmethod
    def start_engine(self) -> None:
        pass

    @abstractmethod
    def stop_engine(self) -> None:
        pass

    @abstractmethod
    def get_installed_models(self) -> List[str]:
        pass

    @abstractmethod
    def set_model_name(self, model_name: str) -> None:
        pass

    @abstractmethod
    def set_api_key(self, api_key: str) -> None:
        pass

    @abstractmethod
    def get_context_size(self) -> int:
        pass

    @abstractmethod
    def request(self, context: List[Dict[str, str]], model: Optional[str] = None, options: Optional[Dict[str, Any]] = None, chunk_callback: Optional[Any] = None) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_insight_scan_option(self) -> Dict[str, Any]:
        pass