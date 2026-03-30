from llm_client.google_studio_manager import GoogleStudioManager
from llm_client.ollama_manager import OllamaManager

class LLMRequester:
    def __init__(self):
        self.client_type = None
        self.ollama_manager = OllamaManager()
        self.google_studio_manager = GoogleStudioManager()
        self.client = None
        self.chunk_count = [0]

        self.chunck_spinner = [
    # --- [1단계: 기초 형태 기동 (안정적 시작)] ---
    "◐", "◓", "◑", "◒", "◜", "◠", "◝", "◞", "◡", "◟",
    
    # --- [2단계: 바이너리 및 시스템 로직 심문 (글리치 A)] ---
    "0", "1", "0", "1", "0", "1",
    "[", "{", "}", "]", "(", ")", "/", "\\", "|", "!", "?", "#", "&", "%",
    "0x", "A", "0x", "F", "0x", "3", "0x", "9", "A", "C", "I", "D",
    
    # --- [3단계: 수사관의 날카로운 직감 (아이콘 깜빡임 A)] ---
    "🧠", "🧐", "🔎", "🕵️‍♂️", "📝", "📊", "📈", "📉", "⏱️", "⏲️",
    
    # --- [4단계: 트레이스 트리 전수 조사 (브라일 패턴 폭주)] ---
    "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏", 
    "⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷",
    "⢄", "⢂", "⢁", "⡈", "⡐", "⡠", "⡠", "⡐", "⡈", "⢁", "⢂", "⢄",
    
    # --- [5단계: 시스템 병목 및 스파이크 감지 (하이테크 글리치)] ---
    "░", "▒", "▓", "█", "▓", "▒", "░",
    "▖", "▗", "▝", "▘", "■", "□", "▢", "▣", "▤", "▥", "▦", "▧", "▨", "▩",
    "---", "-+-", "+++", "-+-", "---",
    
    # --- [6단계: 수학적 가설 검증 (추상적 추론)] ---
    "∑", "∏", "∫", "∂", "∆", "∇", "≈", "≠", "≡",
    "√", "∞", "∝", "∠", "⊥", "∥",
    
    # --- [7단계: 안드로이드 커널의 심연 (아이콘 깜빡임 B)] ---
    "⚡", "⚙️", "🛠️", "🔧", "🔌", "⚠️", "🚨", "🛑",
    "🤖", "🍃", "🍦", "🍭", "🥧", "🍰", "🎂",
    
    # --- [8단계: 최종 판결 및 기소 (서사적 마무리)] ---
    "⚖️", "🏛️", "🔨", "💯", "✅", "❌",
    
    # --- [9단계: 재부팅 (초기 형태로 복귀)] ---
    "⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷",
    "◯", "🟢", "⚫", "🔴", "🔵", "🟡"
]

    def chunk_callback(self, chunk, output_callback=None):
        if chunk is None:
            self.chunk_count[0] = 0
            if output_callback:
                output_callback("", False)
            return

        # [수사관의 실시간 사고 흐름 - 영문 문장형]
        status_phrases = [
            # STAGE 1: Arrival & Link
            "Investigator arriving at scene",   # 현장 도착
            "Securing neural forensic link",    # 신경망 링크 확보
            "Igniting deep reasoning engine",   # 추론 엔진 가동
            # STAGE 2: Evidence Mapping
            "Sifting through trace evidence",   # 트레이스 조사
            "Tracking Android thread flow",     # 스레드 추적
            "Mapping evidence tree structure",  # 트리 구조 매핑
            # STAGE 3: Clue Detection
            "Scanning for scheduling gaps",     # 스케줄링 갭 탐색
            "Detecting Binder spam patterns",   # 바인더 스팸 감지
            "Checking resource contention",     # 자원 경합 확인
            # STAGE 4: Reasoning
            "Cross-referencing alibis",         # 알리바이 대조
            "Analyzing System vs App fault",    # 책임 비중 분석
            "Deducing hidden kernel delays",    # 커널 지연 추론
            # STAGE 5: Finalizing
            "Compiling forensic report",        # 보고서 컴파일
            "Translating technical insights",   # 인사이트 번역
            "Finalizing the ultimate verdict"   # 최종 판결 확정
        ]
        
        phrase_idx = (self.chunk_count[0] // 15) % len(status_phrases)
        spinner_idx = (self.chunk_count[0] // 3) % len(self.chunck_spinner)
        
        current_status = status_phrases[phrase_idx]
        current_symbol = self.chunck_spinner[spinner_idx]
        
        spinner_msg = f"\r🔍 {current_status.ljust(40)} {current_symbol}"
        
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