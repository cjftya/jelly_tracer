from dataclasses import dataclass
from typing import Any


@dataclass
class AnalysisContext:
    common_api: Any
    target_package: str
    llm_requester: Any
    event_poster: Any