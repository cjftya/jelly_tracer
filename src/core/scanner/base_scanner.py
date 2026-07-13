from typing import Optional, List, Any

class BaseScanner:
    def __init__(self):
        self.output_callback = None
        self.llm_requester = None
        self.target_package = None

    def start(self, common_api, target_package, llm_requester, output_callback):
        self.target_package = target_package
        self.output_callback = output_callback
        self.llm_requester = llm_requester

    def stop(self):
        self.llm_requester = None
        self.output_callback = None

    def run(self, output_callback=None) -> Optional[List[Any]]:
        if output_callback:
            self.output_callback = output_callback