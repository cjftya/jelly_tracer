import os
import subprocess
import time

from ollama import Client


class OllamaManager:

    def __init__(self, model_name):
        self.__model_name = model_name

        self._start_optimized_engine()

        self.__options = {
            "num_ctx": 16384,          # 수사 기록 유지를 위한 16k 확보
            "num_gpu": 99,             # VRAM(4~6GB)을 꽉 채우고 나머지는 시스템 RAM으로 오프로드
            "num_thread": 8,           # CPU 추론 비중이 높으므로 코어 활용 극대화
            "temperature": 0,          # 데이터 수치에 대한 엄격한 해석 (냉철함)
            "top_p": 0.9,              # 논리적 일관성 유지
            "repeat_penalty": 1.1,     # 무의미한 루프 방지
            "num_predict": 4096,       # [추가] 상세 보고서 작성을 위한 출력 길이 확보
            "mirostat": 0,             # 예측 불가능성 제거 (안정성)
            "low_vram": False,         # 적극적인 GPU 활용 모드
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
            keep_alive=False,
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
        print("🚀 기존 Ollama 세션을 정리증...")
        subprocess.run(
            ["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, text=True
        )
        time.sleep(5)
        print("✅ 완료")


        print("🚀 전용 환경을 활성화 설정중...")
        forensic_env = os.environ.copy()
        forensic_env["OLLAMA_FLASH_ATTENTION"] = "1"  # 연산 가속
        forensic_env["OLLAMA_KV_CACHE_TYPE"] = "q4_0"  # 기억 장치 압축 (VRAM 절약 핵심)
        forensic_env["OLLAMA_NUM_PARALLEL"] = "1"  # 자원 독점
        forensic_env["OLLAMA_MAX_LOADED_MODELS"] = "1"  # 메모리 혼선 방지
        forensic_env["GGML_CUDA_ENABLE_UNIFIED_MEMORY"] = "1"
        forensic_env["CUDA_MODULE_LOADING"] = "LAZY"

        subprocess.Popen(
            ["ollama", "serve"],
            env=forensic_env,
            creationflags=subprocess.CREATE_NO_WINDOW,  # 창 없이 조용히 실행
        )
        time.sleep(5)
        print("✅ 완료")
