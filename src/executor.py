from detective_api import DetectiveAPI
from ollama_manager import OllamaManager
from prompt_values import PromptValues
import json

class Executor:
    def __init__(self, model_name='gemma3-12b'):
        self.ollamaManager = OllamaManager(model_name=model_name)

    def run(self, trace_normal, trace_slow, output_callback=None, target_name=None):
        def _out(msg: str):
            if output_callback:
                output_callback(msg)
            else:
                print(msg)
            lines.append(msg)

        lines: list[str] = []
        
        spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        chunk_count = [0]
        
        def chunk_callback(chunk):
            spinner_msg = f"\r💬 응답 수신 중... {spinner[chunk_count[0] % len(spinner)]}"
            if output_callback:
                output_callback(spinner_msg)
            else:
                print(spinner_msg, end='', flush=True)
            chunk_count[0] += 1
        
        det_n = DetectiveAPI(trace_normal)
        det_s = DetectiveAPI(trace_slow)
        context = [
            {'role': 'system', 'content': PromptValues.getSystemPrompt(target_name=target_name)},
            {'role': 'user', 'content': f"수사 개시! API 1 결과:\n[Normal]\n{det_n.get_milestones()}\n\n[Slow]\n{det_s.get_milestones()}"}
        ]
    
        _out("🕵️‍♂️ 분석을 시작합니다...")
        while True:
            response = self.ollamaManager.request(context, format='json', chunk_callback=chunk_callback)
            
            result = json.loads(response['message']['content'])
            thought = result.get('thought', '추론 중...')
            _out(f"\n🧠 생각: {thought}")

            if result['status'] == 'investigating':
                api_requests = result.get('call_apis', [])
                combined_feedback = "### 추가 수사 결과 보고 ###\n"
                
                for req in api_requests:
                    num = req['number']
                    target = req.get('target_process')
                    _out(f"🚀 API {num} 호출 중... (타겟: {target if target else '전체'})")
                    
                    if num == 2:
                        data_n, data_s = det_n.get_main_thread_heavy(target), det_s.get_main_thread_heavy(target)
                    elif num == 3:
                        data_n, data_s = det_n.get_binder_calls(target), det_s.get_binder_calls(target)
                    elif num == 4:
                        data_n, data_s = det_n.get_cpu_states(target), det_s.get_cpu_states(target)
                    
                    combined_feedback += f"\n[API {num} 결과 - 타겟: {target}]\nNormal:\n{data_n}\nSlow:\n{data_s}\n"

                context.append({'role': 'assistant', 'content': json.dumps(result)})
                context.append({'role': 'user', 'content': combined_feedback})
                
            elif result['status'] == 'complete':
                report = result['final_report']
                _out("\n✨ 분석 완료! ✨")
                _out(f"🚩 요약: {report['summary']}")
                _out("-" * 50)
                _out(report['analysis'])
                _out("-" * 50)
                _out(f"💡 해결책: {report['solution']}")
                break

        return lines