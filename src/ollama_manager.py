import os
import subprocess
import time

from ollama import Client


class OllamaManager:

    def __init__(self, model_name):
        self.__model_name = model_name

        self._start_optimized_engine()

        self.__options = {
            "num_ctx": 16384,  # 16k로 고정
            "num_gpu": 99,  # 모든 레이어를 GPU로 던집니다. (부족분은 알아서 CPU가 처리)
            "num_thread": 8,  # CPU가 개입할 때 사용할 엔진 코어 수 (i5/i7 최적값)
            "temperature": 0,  # 헛소리 방지용 냉철함 유지
            "top_p": 0.9,  # 분석의 일관성 확보
            "repeat_penalty": 1.1,  # 같은 말 반복 수사 방지
            "f16_kv": True,  # 절반 정밀도로 기억력 효율 증대
            "low_vram": False,  # Ollama가 적극적으로 GPU를 쓰도록 강제
        }
        None

    def get_context_size(self):
        return self.__options.get("num_ctx", 0)

    def request(self, context, format=None, chunk_callback=None):
        client = Client(host="http://127.0.0.1:11434")
        response_stream = client.chat(
            model=self.__model_name,
            messages=context,
            format=format,
            options=self.__options,
            stream=True,
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

    def _start_optimized_engine(self):
        print("🕵️‍♂️ 기존 Ollama 세션을 정리하고 전용 환경을 활성화합니다...")

        subprocess.run(
            ["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, text=True
        )

        forensic_env = os.environ.copy()
        forensic_env["OLLAMA_FLASH_ATTENTION"] = "1"  # 연산 가속
        forensic_env["OLLAMA_KV_CACHE_TYPE"] = "q4_0"  # 기억 장치 압축 (VRAM 절약 핵심)
        forensic_env["OLLAMA_NUM_PARALLEL"] = "1"  # 자원 독점
        forensic_env["OLLAMA_MAX_LOADED_MODELS"] = "1"  # 메모리 혼선 방지

        # 메모리 파편화를 막아 0.13초 지연 분석 중 'Out of Memory' 에러를 방지합니다.
        forensic_env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        # 부족한 VRAM을 시스템 RAM으로 유연하게 확장합니다. (2라운드 느려짐 완화)
        forensic_env["GGML_CUDA_ENABLE_UNIFIED_MEMORY"] = "1"
        forensic_env["CUDA_MODULE_LOADING"] = "LAZY"

        subprocess.Popen(
            ["ollama", "serve"],
            env=forensic_env,
            creationflags=subprocess.CREATE_NO_WINDOW,  # 창 없이 조용히 실행
        )

        print("⏳ 환경 설정 완료 중 (5초)...")
        time.sleep(5)
