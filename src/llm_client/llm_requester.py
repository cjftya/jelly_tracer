from typing import Dict, Any, List, Optional
from llm_client.base_client import BaseClient

class LLMClientFactory:
    @staticmethod
    def create_client(client_type: str) -> BaseClient:
        if client_type == "ollama":
            from llm_client.ollama_manager import OllamaManager
            return OllamaManager()
        elif client_type == "google_studio":
            from llm_client.google_studio_manager import GoogleStudioManager
            return GoogleStudioManager()
        else:
            raise ValueError(f"Unknown client type: {client_type}")


class LLMRequester:
    def __init__(self):
        self.client_type = None
        self.client: Optional[BaseClient] = None
        self.chunk_count = [0]

        self.chunck_spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.pretty_emojis = ["🔍", "🧠", "⚙️", "🔬", "📡", "💠", "💎", "✨"]
        
    def chunk_callback(self, chunk, output_callback=None):
        if chunk is None:
            self.chunk_count[0] = 0
            if output_callback:
                output_callback("", False)
            return

        status_text = "Thinking..."

        # 18청크마다 사고 흐름 이모지 교체
        emoji_idx = (self.chunk_count[0] // 18) % len(self.pretty_emojis)
        # 2청크마다 10프레임 브라유 스피너 회전
        spinner_idx = (self.chunk_count[0] // 2) % len(self.chunck_spinner)
        
        current_emoji = self.pretty_emojis[emoji_idx]
        current_symbol = self.chunck_spinner[spinner_idx]
        
        spinner_msg = f"\r{current_emoji} {status_text} {current_symbol}"
        
        if output_callback:
            output_callback(spinner_msg, False)
            
        self.chunk_count[0] += 1

    def init_client(self, client_type):
        if self.client_type == client_type:
            return
            
        self.client_type = client_type
        self.client = LLMClientFactory.create_client(client_type)

    def request(self, context, model=None, options=None, chunk_callback=None):
        if not self.client:
            raise RuntimeError("LLM Client has not been initialized.")
        return self.client.request(context, model, options, chunk_callback)

    def start_engine(self, full=False):
        if full:
            from llm_client.ollama_manager import OllamaManager
            from llm_client.google_studio_manager import GoogleStudioManager
            # 기동 가능한 모든 클라이언트 백그라운드 엔진 기동
            try:
                OllamaManager().start_engine()
            except Exception as e:
                print(f"Ollama startup failed: {e}")
            try:
                GoogleStudioManager().start_engine()
            except Exception as e:
                print(f"Google Studio startup failed: {e}")
        else:
            if self.client:
                self.client.start_engine()

    def stop_engine(self, full=False):
        if full:
            from llm_client.ollama_manager import OllamaManager
            from llm_client.google_studio_manager import GoogleStudioManager
            try:
                OllamaManager().stop_engine()
            except Exception as e:
                print(f"Ollama shutdown failed: {e}")
            try:
                GoogleStudioManager().stop_engine()
            except Exception as e:
                print(f"Google Studio shutdown failed: {e}")
        else:
            if self.client:
                self.client.stop_engine()

    def get_installed_models(self):
        if not self.client:
            return []
        return self.client.get_installed_models()

    def set_model_name(self, model_name):
        if self.client:
            self.client.set_model_name(model_name)

    def set_api_key(self, api_key):
        if self.client:
            self.client.set_api_key(api_key)

    def get_context_size(self):
        if not self.client:
            return 0
        return self.client.get_context_size()

    def get_insight_scan_option(self):
        if not self.client:
            return {}
        return self.client.get_insight_scan_option()