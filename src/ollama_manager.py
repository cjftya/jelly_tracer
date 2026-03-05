from ollama import Client

class OllamaManager:

    def __init__(self, model_name):
        self.__model_name = model_name
        self.__options = {
            'num_ctx': 32768,
            'temperature': 0.1,
            'top_p': 0.9,
            'repeat_penalty': 1.1
            }
        None

    def request(self, context, format=None, chunk_callback=None):
        client = Client(host="http://127.0.0.1:11434")
        response_stream = client.chat(
            model=self.__model_name,
            messages=context,
            format=format,
            options=self.__options,
            stream=True
        )
        
        full_response = {'message': {'content': ''}}
        for chunk in response_stream:
            if 'message' in chunk and 'content' in chunk['message']:
                content = chunk['message']['content']
                full_response['message']['content'] += content
                # chunk_callback이 제공되면 각 chunk마다 호출
                if chunk_callback:
                    chunk_callback(content)
        
        return full_response