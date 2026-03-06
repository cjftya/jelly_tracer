from ollama import Client


class OllamaManager:

    def __init__(self, model_name):
        self.__model_name = model_name
        self.__options = {
            "num_ctx": 32768,
            "temperature": 0.1,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
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

        return full_response
