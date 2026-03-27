import os
import subprocess
import time
import signal

import platform
from ollama import Client


class OllamaManager:
    def __init__(self):
        self.__process = None 
        self.os_type = platform.system()
        self.local_url = "127.0.0.1"
        self.test_url = "192.168.45.252"
        self.base_url = f"http://{self.test_url}:11434"
        self.model_names = []
        self.__model_name = None
        self.chunk_count = [0]
        
        self.__default_options = {
            "num_ctx": 16384,
            "temperature": 0,
            "top_p": 0.8,
            "repeat_penalty": 1.05,
            "num_predict": 4096,
            "low_vram": True
        }

        

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

    def getL1Option(self):
        return {
            "num_ctx": 16384,
            "temperature": 0,
            "top_p": 1.0,
            "repeat_penalty": 1.05,
            "num_predict": 2048,
            "num_thread": 8,
            "low_vram": True
        }

    def getL2Phase1Option(self):
        return {
            "num_ctx": 16384,
            "temperature": 0,
            "top_p": 1.0,
            "repeat_penalty": 1.15,
            "num_predict": 4096,
            "num_thread": 8,
            "low_vram": True
        }

    def getL2Phase2Option(self):
        return {
            "num_ctx": 16384,
            "temperature": 0.2,
            "top_p": 0.85,
            "repeat_penalty": 1.2,
            "num_predict": 2048,
            "low_vram": True
        }

    def get_report_only_model(self):
        for model_name in self.model_names:
            if "gemma3" in model_name:
                return model_name
        return "gemma3"

    def get_installed_models(self):
        client = Client(host=self.base_url)
        response = client.list()
        self.model_names = [model.model for model in response.models]
        return self.model_names

    def set_model_name(self, model_name):
        self.__model_name = model_name

    def get_context_size(self):
        return self.getL1Option().get("num_ctx", 0)

    def request(self, context, model=None, options=None, format=None, chunk_callback=None):
        client = Client(host=self.base_url)
        op = self.__default_options.copy()
        if options:
            op = options

        response_stream = client.chat(
            model=model if model else self.__model_name,
            messages=context,
            format=format,
            options=op,
            stream=True,
            keep_alive=0
        )

        full_response = {"message": {"content": ""}}
        for chunk in response_stream:
            if "message" in chunk and "content" in chunk["message"]:
                content = chunk["message"]["content"]
                full_response["message"]["content"] += content
                if chunk_callback:
                    chunk_callback(content)

            if "prompt_eval_count" in chunk:
                full_response["prompt_eval_count"] = chunk["prompt_eval_count"]
            if "eval_count" in chunk:
                full_response["eval_count"] = chunk["eval_count"]

        return full_response

    def start_engine(self):
        self.stop_engine() 
        
        print("🚀 Initializing LLM Analysis Environment...")
        forensic_env = os.environ.copy()
        forensic_env["OLLAMA_FLASH_ATTENTION"] = "1"
        forensic_env["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
        forensic_env["OLLAMA_NUM_PARALLEL"] = "1"

        self.__process = subprocess.Popen(
            ["ollama", "serve"],
            env=forensic_env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(5)
        print("✅ Complete")

    def stop_engine(self):
        print("🚀 Cleaning up LLM Session...")
        if self.__process:
            self.__process.terminate()
            self.__process.wait()
            self.__process = None
        
        if self.os_type == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/IM", "ollama.exe", "/T"], 
                capture_output=True, 
                text=True
            )
        else:
            subprocess.run(
                ["pkill", "-f", "ollama"],
                capture_output=True,
                text=True
            )
        print("✅ Complete")