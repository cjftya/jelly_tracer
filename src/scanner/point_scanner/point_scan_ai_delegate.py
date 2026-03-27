import re
from scanner.point_scanner.point_scan_prompt_values import PointScanPromptValues
from ollama_manager import OllamaManager

class PointScanAIDelegate:
    def __init__(self, ollama_manager: OllamaManager, output_callback):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.thought_archive = []

    def request_analysis(self, context_dict):
        context_text = (
            f"[Investigation Context]\n"
            f"- Target Thread: {context_dict['thread_name']}\n"
            f"- Thread Metadata: {context_dict['utid_info']}\n\n"
            f"[Performance JSON Data]\n"
            f"{context_dict['tree_data']}\n\n"
            f"Analyze cases and select the primary suspect based on 'Selection Logic'."
        )
        
        contents = [
            {"role": "system", "content": PointScanPromptValues.getSystemPrompt()},
            {"role": "user", "content": context_text}
        ]

        response = self.ollama_manager.request(
            context=contents, 
            options=self.ollama_manager.getL1Option(),
            chunk_callback=lambda chunk: self.ollama_manager.chunk_callback(chunk, self.output_callback)
        )

        raw_result = response["message"]["content"] if isinstance(response, dict) and "message" in response else str(response)

        # ---------------------------------------------------------
        # 🎯 앵커 기반 정밀 파싱
        # ---------------------------------------------------------
        thought_anchor = "[[THOUGHT]]"
        result_anchor = "**[Selected Slice]**"
        
        thought_content = ""
        final_report = raw_result

        if result_anchor in raw_result:
            parts = raw_result.split(result_anchor)
            raw_thought = parts[0].replace(thought_anchor, "").strip()
            clean_thought = re.sub(r'^\[+|(?:\]+/*)+$', '', raw_thought).strip()
            thought_content = clean_thought
            final_report = f"{result_anchor}{parts[1]}".strip()
        else:
            final_report = re.sub(r'\[+THOUGHT\]+|\[+|\]+', '', raw_result).strip()

        if thought_content:
            self.thought_archive.append(thought_content)
            if self.output_callback:
                self.output_callback("\n🧠 [Forensic Reasoning Archived: Logic Logged]", True)

        total_tokens = response.get("prompt_eval_count", 0) + response.get("eval_count", 0)
        if self.output_callback:
            self.output_callback(f"\\token {total_tokens}")

        processed_res = {
            "thinking": thought_content,
            "analysis": final_report,
            "raw": raw_result
        }

        return processed_res