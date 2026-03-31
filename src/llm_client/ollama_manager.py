import os
import subprocess
import time
import signal
import platform
from ollama import Client
from llm_client.base_client import BaseClient


class OllamaManager(BaseClient):
    def __init__(self):
        self.__process = None 
        self.os_type = platform.system()
        self.local_url = "127.0.0.1"
        self.test_url = "192.168.45.171"
        self.base_url = f"http://{self.local_url}:11434"
        self.model_names = []
        self.__model_name = None
        self.__default_options = {
            "num_ctx": 16384,
            "temperature": 0,
            "top_p": 1.0,
            "repeat_penalty": 1.15,
            "num_predict": 4096,
            "num_thread": 8,
            "low_vram": True
        }

    def getInsightScanOption(self):
        return self.__default_options.copy()

    def get_installed_models(self):
        client = Client(host=self.base_url)
        response = client.list()
        self.model_names = [model.model for model in response.models]
        return self.model_names

    def set_model_name(self, model_name):
        self.__model_name = model_name

    def set_api_key(self, api_key):
        # Ollama usually doesn't need an API key for local use, but we keep the method for consistency
        pass

    def get_context_size(self):
        return 16384

    def __str__(self):
        return f"OllamaManager(base_url={self.base_url}, model={self.__model_name})"

    def request(self, context, model=None, options=None, chunk_callback=None):
        client = Client(host=self.base_url)
        op = options if options else self.__default_options.copy()
        
        response_stream = client.chat(
            model=model if model else self.__model_name,
            messages=context,
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

        if self.os_type == "Windows":
            self.__process = subprocess.Popen(
                ["ollama", "serve"],
                env=forensic_env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            self.__process = subprocess.Popen(
                ["ollama", "serve"],
                env=forensic_env,
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