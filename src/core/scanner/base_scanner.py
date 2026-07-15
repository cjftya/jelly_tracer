from typing import Optional

from core.analysis_context import AnalysisContext


class BaseScanner:
    def __init__(self):
        self.context: Optional[AnalysisContext] = None

    def start(self, context: AnalysisContext) -> None:
        self.context = context

    def require_context(self) -> AnalysisContext:
        if self.context is None:
            raise RuntimeError("Analysis context has not been initialized.")
        return self.context

    def stop(self) -> None:
        self.context = None
