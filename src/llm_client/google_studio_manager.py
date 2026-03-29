from google import genai
from google.genai import types
from llm_client.base_client import BaseClient

class GoogleStudioManager(BaseClient):
    def __init__(self):
        self._api_key = None
        self.__model_name = None

    def set_api_key(self, api_key):
        self._api_key = api_key

    def getInsightScanOption(self):
        return {
            "temperature": 0,
            "max_output_tokens": 4096,
            "top_p": 1.0,
        }

    def get_installed_models(self):
        return ["gemma-3-4b-it", "gemma-3-12b-it"]

    def set_model_name(self, model_name):
        self.__model_name = model_name

    def get_context_size(self):
        return 16384

    def request(self, context, model=None, options=None, chunk_callback=None):
        client = genai.Client(api_key=self._api_key)
        
        # 1. 사용할 모델 확정 (None 방어)
        target_model = model if model else self.__model_name
        if not target_model:
            target_model = "gemma-3-12b-it" # 최후의 보루

        system_prompt = ""
        user_content = ""
        
        # 2. 컨텍스트 파싱
        if isinstance(context, list):
            for msg in context:
                if msg.get("role") == "system":
                    system_prompt = msg.get("content") or ""
                elif msg.get("role") == "user":
                    user_content = msg.get("content") or ""
        else:
            user_content = context or ""

        # 3. Gemma 모델 전용 '프롬프트 병합' 로직 (변수 이름 통일)
        # target_model이 문자열임을 보장하므로 .lower() 사용 가능
        if "gemma" in target_model.lower():
            # Gemma는 system_instruction 칸을 쓰면 400 에러가 나므로 합쳐줍니다.
            actual_contents = f"[지침]\n{system_prompt}\n\n[데이터]\n{user_content}"
            final_system_instruction = None 
        else:
            # Gemini 등은 전용 칸 사용 가능
            actual_contents = user_content
            final_system_instruction = system_prompt

        # 4. 설정 구성
        op = options.copy() if options else self.getInsightScanOption()
        request_config = {
            "system_instruction": final_system_instruction,
            "temperature": op.get("temperature", 0),
            "max_output_tokens": op.get("max_output_tokens", 4096),
            "top_p": op.get("top_p", 1.0),
        }

        try:
            response_stream = client.models.generate_content_stream(
                model=target_model,
                contents=actual_contents, # 병합된 내용을 전달!
                config=request_config
            )

            full_response = {"message": {"content": ""}}
            for chunk in response_stream:
                if chunk.text:
                    text = chunk.text
                    full_response["message"]["content"] += text
                    if chunk_callback:
                        chunk_callback(text)
            
                if hasattr(chunk, 'candidates') and chunk.candidates:
                    finish_reason = chunk.candidates[0].finish_reason
                    if finish_reason == "SAFETY":
                        print("\n🚨 [보안 경보] 안전 필터에 의해 답변이 차단되었습니다!")

            usage = getattr(response_stream, 'usage_metadata', None)
            if usage:
                full_response["prompt_eval_count"] = getattr(usage, 'prompt_token_count', 0)
                full_response["eval_count"] = getattr(usage, 'candidates_token_count', 0)
            else:
                full_response["prompt_eval_count"] = 0
                full_response["eval_count"] = 0

            return full_response
            
        except Exception as e:
            print(f"🚨 [Error] {e}")
            return {"message": {"content": f"Error: {str(e)}"}, "prompt_eval_count": 0, "eval_count": 0}