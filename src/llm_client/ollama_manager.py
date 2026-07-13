import os
import subprocess
import time
import signal
import platform
from ollama import Client
from llm_client.base_client import BaseClient
from typing import Dict, Any, List, Optional


class OllamaManager(BaseClient):
    def __init__(self):
        self.__process: Optional[subprocess.Popen] = None 
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

    def get_insight_scan_option(self) -> Dict[str, Any]:
        return self.__default_options.copy()

    def get_installed_models(self) -> List[str]:
        client = Client(host=self.base_url)
        response = client.list()
        self.model_names = [model.model for model in response.models if model.model]
        return self.model_names

    def set_model_name(self, model_name: str) -> None:
        self.__model_name = model_name

    def set_api_key(self, api_key: str) -> None:
        # Ollama usually doesn't need an API key for local use, but we keep the method for consistency
        pass

    def get_context_size(self) -> int:
        return 16384

    def __str__(self):
        return f"OllamaManager(base_url={self.base_url}, model={self.__model_name})"

    def request(self, context: List[Dict[str, str]], model: Optional[str] = None, options: Optional[Dict[str, Any]] = None, chunk_callback: Optional[Any] = None) -> Dict[str, Any]:
        client = Client(host=self.base_url)
        op = options if options else self.__default_options.copy()
        
        # 1. 사용할 모델 확정 (None 방어)
        temp_model = model if model else self.__model_name
        target_model: str = temp_model if temp_model else ""
        if not target_model:
            installed = self.model_names if self.model_names else self.get_installed_models()
            target_model = installed[0] if installed else "gemma-3-12b-it"

        try:
            response_stream = client.chat(
                model=target_model,
                messages=context,  # type: ignore
                options=op,
                stream=True,
                keep_alive=0
            )

            full_response = {
                "message": {"content": ""},
                "prompt_eval_count": 0,
                "eval_count": 0,
                "error": None
            }
            for chunk in response_stream:
                chunk_dict: Any = chunk
                if "message" in chunk_dict and "content" in chunk_dict["message"]:
                    content = chunk_dict["message"]["content"]
                    full_response["message"]["content"] += content
                    if chunk_callback:
                        chunk_callback(content)

                if "prompt_eval_count" in chunk_dict:
                    full_response["prompt_eval_count"] = chunk_dict["prompt_eval_count"]
                if "eval_count" in chunk_dict:
                    full_response["eval_count"] = chunk_dict["eval_count"]

            return full_response
        except Exception as e:
            print(f"🚨 [Ollama Error] {e}")
            return {
                "message": {"content": ""},
                "prompt_eval_count": 0,
                "eval_count": 0,
                "error": f"Error: {str(e)}"
            }

    def start_engine(self) -> None:
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

    def stop_engine(self) -> None:
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