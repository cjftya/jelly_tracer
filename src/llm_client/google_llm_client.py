from typing import Any, Dict, Optional

from google import genai
from google.genai import types

from llm_client.base_client import BaseClient


class GoogleLLMClient(BaseClient):
    def __init__(self, api_key: Optional[str] = None):
        self._model_name = "gemini-3.1-flash-lite"
        self.client = None
        self.set_api_key(api_key)

    def set_api_key(self, api_key: Optional[str]) -> None:
        self.client = genai.Client(api_key=api_key) if api_key else None

    def get_model_name(self) -> str:
        return self._model_name

    def get_options(self) -> Dict[str, Any]:
        return {"temperature": 0.1, "top_p": 0.9, "top_k": 40}

    def request(self, context: Any, options=None, chunk_callback=None) -> Dict[str, Any]:
        if not self.client:
            return self._response(error="API key is not set.")

        system_instruction, contents = self._contents(context)
        request_options = self.get_options()
        if options:
            request_options.update(options)

        config = {
            "system_instruction": system_instruction,
            "temperature": request_options.get("temperature"),
            "top_p": request_options.get("top_p"),
            "top_k": request_options.get("top_k"),
        }
        if request_options.get("max_output_tokens") is not None:
            config["max_output_tokens"] = request_options["max_output_tokens"]

        try:
            response = self.client.models.generate_content_stream(
                model=self._model_name,
                contents=contents,
                config=types.GenerateContentConfig(**config),
            )
            chunks = []
            for chunk in response:
                text = getattr(chunk, "text", None)
                if text:
                    chunks.append(text)
                    if chunk_callback:
                        chunk_callback(text)

            usage = getattr(response, "usage_metadata", None)
            return self._response(
                content="".join(chunks),
                prompt_tokens=getattr(usage, "prompt_token_count", 0),
                completion_tokens=getattr(usage, "candidates_token_count", 0),
            )
        except Exception as error:
            return self._response(error=str(error))

    @staticmethod
    def _contents(context: Any):
        system_messages = []
        contents = []
        messages = (
            context
            if isinstance(context, list)
            else [{"role": "user", "content": context}]
        )

        for message in messages:
            if not isinstance(message, dict):
                contents.append(str(message))
                continue

            content = message.get("content") or ""
            if message.get("role") == "system":
                system_messages.append(content)
            else:
                contents.append(content)

        return "\n\n".join(system_messages) or None, contents or [""]

    @staticmethod
    def _response(content="", prompt_tokens=0, completion_tokens=0, error=None):
        return {
            "message": {"content": content},
            "prompt_eval_count": prompt_tokens,
            "eval_count": completion_tokens,
            "error": error,
        }