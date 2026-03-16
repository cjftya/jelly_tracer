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
        
        self.__options = {
            "num_ctx": 24576,
            "temperature": 0,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "num_predict": 2048,
            "mirostat": 0,
            "low_vram": True
        }

    def get_installed_models(self):
        client = Client(host="http://127.0.0.1:11434")
        response = client.list()
        return [model.model for model in response.models]

    def set_model_name(self, model_name):
        self.__model_name = model_name

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
            keep_alive=0,
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

    def request_text(self, prompt: str):
        client = Client(host="http://127.0.0.1:11434")
        response = client.generate(
            model=self.__model_name,
            prompt=prompt,
            options=self.__options,
            keep_alive=0,
        )
        return response.get("response", "")

    def start_engine(self):
        self.stop_engine() 
        
        print("🚀 LLM 분석 환경 설정중...")
        forensic_env = os.environ.copy()
        forensic_env["OLLAMA_FLASH_ATTENTION"] = "1"
        forensic_env["OLLAMA_KV_CACHE_TYPE"] = "q4_0"
        forensic_env["OLLAMA_NUM_PARALLEL"] = "1"
        forensic_env["OLLAMA_MAX_LOADED_MODELS"] = "1"

        self.__process = subprocess.Popen(
            ["ollama", "serve"],
            env=forensic_env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(5)
        print("✅ 완료")

    def stop_engine(self):
        print("🚀 LLM 세션 정리중...")
        
        if self.__process:
            self.__process.terminate()
            self.__process.wait()
            self.__process = None
        
        if self.os_type == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/IM", "ollama.exe"], 
                capture_output=True, 
                text=True
            )
        else:
            subprocess.run(
                ["pkill", "-f", "ollama"],
                capture_output=True,
                text=True
            )
    
        print("✅ 완료")