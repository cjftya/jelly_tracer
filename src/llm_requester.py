from llm_client.google_studio_manager import GoogleStudioManager
from llm_client.ollama_manager import OllamaManager

class LLMRequester:
    def __init__(self):
        self.client_type = None
        self.ollama_manager = OllamaManager()
        self.google_studio_manager = GoogleStudioManager()
        self.client = None
        self.chunk_count = [0]

        self.chunck_spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.pretty_emojis = ["🔍", "🧠", "⚙️", "🔬", "📡", "💠", "💎", "✨"]
        
    def chunk_callback(self, chunk, output_callback=None):
        if chunk is None:
            self.chunk_count[0] = 0
            if output_callback:
                output_callback("", False)
            return

        CYAN = "\033[96m"
        RESET = "\033[0m"

        # 텍스트는 진행형인 "Thinking..."으로 고정
        status_text = "Thinking..."
        
        # 이모지 속도: 18청크마다 (너무 자주 바뀌면 산만하므로)
        emoji_idx = (self.chunk_count[0] // 18) % len(self.pretty_emojis)
        # 스피너 속도: 2청크마다 (프레임이 많으므로 분모를 줄여서 회전 속도를 높임)
        spinner_idx = (self.chunk_count[0] // 2) % len(self.chunck_spinner)
        
        current_emoji = self.pretty_emojis[emoji_idx]
        current_symbol = self.chunck_spinner[spinner_idx]
        
        # 출력: \033[K(줄 지우기)와 ljust를 조합하여 완벽한 고정 위치 출력
        spinner_msg = f"{current_emoji} {CYAN}{status_text}{RESET} {current_symbol}" # 예: " 🔬 Thinking... ⠸"
        
        if output_callback:
            output_callback(spinner_msg, False)
            
        self.chunk_count[0] += 1

    def init_client(self, client_type):
        if self.client_type == client_type:
            return
            
        self.client_type = client_type
        if client_type == "ollama":
            self.client = self.ollama_manager
        elif client_type == "google_studio":
            self.client = self.google_studio_manager

    def request(self, context, model=None, options=None, chunk_callback=None):
        return self.client.request(context, model, options, chunk_callback)

    def start_engine(self, full=False):
        if full:
            self.ollama_manager.start_engine()
            self.google_studio_manager.start_engine()
        else:
            self.client.start_engine()

    def stop_engine(self, full=False):
        if full:
            self.ollama_manager.stop_engine()
            self.google_studio_manager.stop_engine()
        else:
            self.client.stop_engine()

    def get_installed_models(self):
        return self.client.get_installed_models()

    def set_model_name(self, model_name):
        self.client.set_model_name(model_name)

    def set_api_key(self, api_key):
        self.client.set_api_key(api_key)

    def get_context_size(self):
        return self.client.get_context_size()

    def getInsightScanOption(self):
        return self.client.getInsightScanOption()