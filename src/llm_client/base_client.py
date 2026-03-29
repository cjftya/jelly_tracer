class BaseClient:
 
    def start_engine(self):
        pass

    def stop_engine(self):
        pass

    def get_installed_models(self):
        pass

    def set_model_name(self, model_name):
        pass

    def set_api_key(self, api_key):
        pass

    def get_context_size(self):
        pass

    def request(self, context, model=None, options=None, chunk_callback=None):
        pass

    def getInsightScanOption(self):
        pass