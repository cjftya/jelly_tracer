from typing import Any, List, Optional


class BaseScanner:
    def __init__(self):
        self.event_poster = None
        self.llm_requester = None
        self.target_package = None

    def start(self, common_api, target_package, llm_requester, event_poster):
        self.target_package = target_package
        self.event_poster = event_poster
        self.llm_requester = llm_requester

    def stop(self):
        self.llm_requester = None
        self.event_poster = None

    def run(self) -> Optional[List[Any]]:
        pass
