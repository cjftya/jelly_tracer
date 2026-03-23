class BaseScanner:
    def __init__(self):
        self.output_callback = None
        self.ollama_manager = None
        self.target_package = None

    def start(self, common_api, target_package, ollama_manager, output_callback):
        self.target_package = target_package
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager

    def run(self, output_callback=None):
        if output_callback:
            self.output_callback = output_callback