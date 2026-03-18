import re
import json
from datetime import datetime
from scanner.insight_scanner.insight_scan_prompt_values import InsightScanPromptValues
from ollama_manager import OllamaManager

class InsightScanAIDelegate:
    def __init__(self, ollama_manager: OllamaManager, output_callback):
        self.output_callback = output_callback
        self.ollama_manager = ollama_manager
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.chunk_count = [0]

    def execute_double_scan(self, master_brief):
        try:
            brief_json = json.dumps(master_brief, separators=(',', ':'))

            # --- Phase 1: Exploration (심연 탐사) ---
            self.output_callback("\n🔍 Phase 1: Deep-Diving into System Internals...")
            p1_context = [
                {"role": "system", "content": InsightScanPromptValues.getPhase1SystemPrompt()},
                {"role": "user", "content": f"Analyze this context:\n{brief_json}"}
            ]
            p1_res = self.ollama_manager.request(p1_context, think_mode=True, num_predict=4096, callback=self._chunk_callback)

            p1_thought = self._extract_thought(p1_res)
            if p1_thought:
                self.output_callback(f"\n\n🤔 [Phase 1: Forensic Hypothesis]\n{p1_thought}\n")

            if not p1_res or "error" in p1_res.lower():
                return "❌ Phase 1 Failure: Invalid response from AI analyst."

            # --- Phase 2: Audit & Verdict (검증 및 기소) ---
            self.output_callback("\n⚖️ Phase 2: Auditing Evidence & Finalizing Report...")
            p2_context = [
                {"role": "system", "content": InsightScanPromptValues.getPhase2SystemPrompt()},
                {"role": "user", "content": f"Audit this reasoning against the ORIGINAL DATA.\n\n[Original Data]\n{brief_json}\n\n[P1 Reasoning]\n{p1_res}"}
            ]
            p2_res = self.ollama_manager.request(p2_context, think_mode=True, num_predict=4096, callback=self._chunk_callback)

            p2_thought = self._extract_thought(p2_res)
            if p2_thought:
                self.output_callback(f"\n\n🧐 [Phase 2: Critical Audit Process]\n{p2_thought}\n")

            final_report = re.sub(r"<think>.*?</think>", "", p2_res, flags=re.DOTALL).strip()

            if "[FINAL_INSIGHT]" in final_report:
                return final_report
            else:
                return f"⚠️ Audit Success but Format Missing:\n{final_report}"

        except Exception as e:
            return f"❌ Critical System Error: {str(e)}"

    def _extract_thought(self, text):
        match = re.search(r"<think>(.*?)</think>", text, re.DOTALL)
        return match.group(1).strip() if match else None

    def _chunk_callback(self, chunk):
        spinner_msg = f"\r💬 Thinking... {self.spinner[self.chunk_count[0] % len(self.spinner)]}"
        if self.output_callback:
            self.output_callback(spinner_msg, False)
        self.chunk_count[0] += 1