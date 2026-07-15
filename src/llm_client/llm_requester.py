from llm_client.google_llm_client import GoogleLLMClient


class LLMRequester:
    def __init__(self):
        self.provider = None
        self.client = None
        self.chunk_count = [0]
        self.chunck_spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.pretty_emojis = ["🔍", "🧠", "⚙️", "🔬", "📡", "💠", "💎", "✨"]

    def chunk_callback(self, chunk, event_poster=None):
        if chunk is None:
            self.chunk_count[0] = 0
            return

        emoji_idx = (self.chunk_count[0] // 18) % len(self.pretty_emojis)
        spinner_idx = (self.chunk_count[0] // 2) % len(self.chunck_spinner)
        spinner_msg = (
            f"\r{self.pretty_emojis[emoji_idx]} Thinking... "
            f"{self.chunck_spinner[spinner_idx]}"
        )
        if event_poster:
            event_poster.log(spinner_msg)
        else:
            print(spinner_msg, end="", flush=True)
        self.chunk_count[0] += 1

    def init_client(self, provider=None, api_key=None):
        if provider:
            self.provider = provider
            self.client = self._create_client(provider, api_key)

    def set_api_key(self, api_key):
        if self.client:
            self.client.set_api_key(api_key)

    def request(self, context, options=None, chunk_callback=None):
        if not self.client:
            return {
                "message": {"content": ""},
                "prompt_eval_count": 0,
                "eval_count": 0,
                "error": "LLM client has not been initialized.",
            }
        return self.client.request(context, options, chunk_callback)

    def start_engine(self):
        if self.client:
            self.client.start_engine()

    def stop_engine(self):
        if self.client:
            self.client.stop_engine()

    def get_model_name(self):
        if self.client:
            return self.client.get_model_name()
        return ""

    def get_insight_scan_option(self):
        if not self.client:
            return {}
        options = self.client.get_options().copy()
        options.update({"temperature": 0, "max_output_tokens": 4096, "top_p": 1.0})
        return options

    @staticmethod
    def _create_client(provider, api_key):
        if provider in {"google", "google_studio"}:
            return GoogleLLMClient(api_key=api_key)
        return None