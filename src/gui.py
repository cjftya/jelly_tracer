import atexit
import io
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from executor import Executor


class ConsoleRedirector:
    def __init__(self, callback, original_stdout=None):
        self.callback = callback
        self.original_stdout = original_stdout

    def write(self, text):
        if text:
            self.callback(text)
            if self.original_stdout:
                self.original_stdout.write(text)

    def flush(self):
        if self.original_stdout:
            self.original_stdout.flush()


class ExecutorThread(threading.Thread):
    def __init__(
        self,
        normal_path: str,
        slow_path: str,
        target_package: str,
        model_name: str = "gemma3-12b",
        executor: Executor = None,
        progress_callback=None,
        token_callback=None,
        finished_callback=None,
    ):
        super().__init__(daemon=True)
        self.normal_path = normal_path
        self.slow_path = slow_path
        self.target_package = target_package
        self.model_name = model_name
        self.executor = executor
        self.progress_callback = progress_callback
        self.token_callback = token_callback
        self.finished_callback = finished_callback
        self.results: list[str] = []
        atexit.register(self.stop)
        self._stop_event = threading.Event()

    def run(self):
        self.token_used = 0
        self.token_total = 0

        def cb(msg: str, system: bool):
            if msg.startswith("\\token"):
                self.token_used += int(msg.replace("\\token", "").strip())
                if self.token_callback:
                    self.token_callback(self.token_used, self.token_total)
            else:
                self.results.append(msg)
                if self.progress_callback:
                    self.progress_callback(msg, system)

        try:
            try:
                # self.executor.start() 는 이제 GUI 시작 시 한 번만 실행됨
                self.token_total = self.executor.ollamaManager.get_context_size()
            except Exception:
                self.token_total = 0
            self.executor.run(
                self.normal_path,
                self.slow_path,
                self.target_package,
                model_name=self.model_name,
                output_callback=cb,
            )
        finally:
            pass
        if self.finished_callback:
            self.finished_callback(self.results)

    def stop(self):
        # 낱개 쓰레드 중단 시 Executor를 끄지 않음
        self._stop_event.set()


class TraceGui(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Trace Analyzer")
        self.geometry("1100x700")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Output Redirection (Redirect print() to System Log & Terminal)
        self.original_stdout = sys.stdout
        sys.stdout = ConsoleRedirector(self._on_stdout_write, self.original_stdout)

        # Theme & Appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.thread: ExecutorThread | None = None
        self.executor = Executor()
        self.console_font_size = 10

        # Configure Grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_ui()

        # 프로그램 시작 시 AI 엔진 및 리소스 매니저 초기화 (딱 한 번)
        if self.status_label:
            self.status_label.configure(text="Initializing System...")
        threading.Thread(target=self._initialize_executor, daemon=True).start()

    def _initialize_executor(self):
        self.executor.start()
        
        # 설치된 모델 목록 가져와서 콤보박스 업데이트
        try:
            models = self.executor.ollamaManager.get_installed_models()
            if models:
                self.after(0, lambda: self.model_combo.configure(values=models))
                # 현재 선택된 모델이 목록에 있으면 유지, 없으면 첫 번째 모델 선택
                current = self.model_combo.get()
                if current not in models:
                    self.after(0, lambda: self.model_combo.set(models[0]))
        except Exception as e:
            print(f"⚠️ 모델 목록 업데이트 실패: {e}")

        self.after(0, lambda: self.status_label.configure(text="System Ready"))

    def _build_ui(self):
        # --- Sidebar ---
        self.sidebar_frame = ctk.CTkFrame(
            self, width=280, corner_radius=0, fg_color="#1A1A1A"
        )
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(10, weight=1)

        # Trace Settings Group
        self.settings_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="CONFIGURATION",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#888888",
            anchor="w",
        )
        self.settings_label.grid(row=0, column=0, padx=25, pady=(40, 10), sticky="w")

        self.package_edit = ctk.CTkEntry(
            self.sidebar_frame,
            placeholder_text="Target package",
            height=40,
            border_width=1,
            fg_color="#242424",
        )
        self.package_edit.insert(0, "com.sec.android.gallery3d")
        self.package_edit.grid(row=1, column=0, padx=25, pady=10, sticky="ew")

        self.model_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="AI Model",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#555555",
            anchor="w",
        )
        self.model_label.grid(row=2, column=0, padx=25, pady=(5, 0), sticky="w")

        self.model_combo = ctk.CTkOptionMenu(
            self.sidebar_frame,
            values=["empty"],
            height=40,
            fg_color="#242424",
            button_color="#333333",
            button_hover_color="#444444",
        )
        self.model_combo.set("model")
        self.model_combo.grid(row=3, column=0, padx=25, pady=(0, 10), sticky="ew")

        # Separator-like padding
        self.path_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="RESOURCES",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#888888",
            anchor="w",
        )
        self.path_label.grid(row=4, column=0, padx=25, pady=(20, 10), sticky="w")

        # Path Selection
        self.path_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.path_frame.grid(row=5, column=0, padx=25, pady=10, sticky="ew")
        self.path_frame.grid_columnconfigure(0, weight=1)

        self.normal_edit = ctk.CTkEntry(
            self.path_frame,
            placeholder_text="Normal trace path",
            height=35,
            fg_color="#242424",
        )
        self.normal_edit.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.btn_n = ctk.CTkButton(
            self.path_frame,
            text="Browse Normal",
            command=lambda: self._choose_path(self.normal_edit),
            height=32,
            fg_color="#333333",
            hover_color="#444444",
            text_color="#AAAAAA",
        )
        self.btn_n.grid(row=1, column=0, sticky="ew", pady=(0, 20))

        self.slow_edit = ctk.CTkEntry(
            self.path_frame,
            placeholder_text="Slow trace path",
            height=35,
            fg_color="#242424",
        )
        self.slow_edit.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        self.btn_s = ctk.CTkButton(
            self.path_frame,
            text="Browse Slow",
            command=lambda: self._choose_path(self.slow_edit),
            height=32,
            fg_color="#333333",
            hover_color="#444444",
            text_color="#AAAAAA",
        )
        self.btn_s.grid(row=3, column=0, sticky="ew")

        # --- Main Content ---
        self.main_container = ctk.CTkFrame(self, corner_radius=0, fg_color="#0F0F0F")
        self.main_container.grid(row=0, column=1, sticky="nsew")
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(3, weight=1)  # Console row should expand
        self.main_container.grid_rowconfigure(0, weight=0)
        self.main_container.grid_rowconfigure(1, weight=0)
        self.main_container.grid_rowconfigure(
            2, weight=0
        )  # Status row should NOT expand

        # Header with Run Button
        self.header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=30, pady=(30, 20))
        self.header_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            self.header_frame,
            text="System Standby",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        self.status_label.grid(row=0, column=0, sticky="w")

        self.run_button = ctk.CTkButton(
            self.header_frame,
            text="INITIALIZE ANALYSIS",
            command=self._on_run,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=45,
            width=180,
            fg_color="#1F538D",
            hover_color="#2666AD",
            corner_radius=5,
        )
        self.run_button.grid(row=0, column=1, sticky="e")

        # Stats Card
        self.stats_frame = ctk.CTkFrame(
            self.main_container,
            corner_radius=8,
            fg_color="#161616",
            border_width=1,
            border_color="#222222",
        )
        self.stats_frame.grid(row=1, column=0, sticky="ew", pady=(0, 30), padx=30)
        self.stats_frame.grid_columnconfigure(0, weight=1)

        self.token_info_frame = ctk.CTkFrame(self.stats_frame, fg_color="transparent")
        self.token_info_frame.pack(fill="x", padx=25, pady=(20, 10))

        self.token_label = ctk.CTkLabel(
            self.token_info_frame,
            text="Tokens: 0 / 0 (0%)",
            font=ctk.CTkFont(family="Consolas", size=13),
            text_color="#888888",
        )
        self.token_label.pack(side="left")

        self.token_bar = ctk.CTkProgressBar(
            self.stats_frame, height=8, progress_color="#1F538D", fg_color="#333333"
        )
        self.token_bar.set(0)
        self.token_bar.pack(fill="x", padx=25, pady=(0, 20))

        # Real-time Status View (Spinner)
        self.realtime_status = ctk.CTkLabel(
            self.main_container,
            text="",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="#888888",
            anchor="w",
            height=25,
        )
        self.realtime_status.grid(row=2, column=0, sticky="ew", padx=35, pady=(0, 2))

        # Console / Terminal View (Split)
        self.console_frame = ctk.CTkFrame(
            self.main_container,
            corner_radius=8,
            fg_color="#121212",
            border_width=1,
            border_color="#222222",
        )
        self.console_frame.grid(row=3, column=0, sticky="nsew", padx=30, pady=(0, 30))
        self.console_frame.grid_rowconfigure(0, weight=1)
        self.console_frame.grid_columnconfigure(0, weight=1)

        # PanedWindow for split view
        self.paned_window = tk.PanedWindow(
            self.console_frame,
            orient=tk.HORIZONTAL,
            bg="#1A1A1A",
            sashwidth=4,
            bd=0,
            sashrelief=tk.FLAT,
        )
        self.paned_window.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        # Left Pane: AI
        self.left_pane = ctk.CTkFrame(
            self.paned_window, fg_color="#0F0F0F", corner_radius=0
        )
        self.left_header = ctk.CTkLabel(
            self.left_pane,
            text=" AI INVESTIGATOR",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#555555",
            anchor="w",
            height=20,
        )
        self.left_header.pack(fill="x", padx=5, pady=(2, 0))

        self.text_edit = ctk.CTkTextbox(
            self.left_pane,
            font=("Consolas", self.console_font_size),
            fg_color="#0F0F0F",
            text_color="#CCCCCC",
            border_width=1,
            border_color="#222222",
            corner_radius=8,
            scrollbar_button_color="#333333",
            scrollbar_button_hover_color="#444444",
            spacing1=5,
            spacing3=5,
        )
        self.text_edit.pack(fill="both", expand=True, padx=5, pady=5)
        self.paned_window.add(self.left_pane, stretch="always")

        # Right Pane: System
        self.right_pane = ctk.CTkFrame(
            self.paned_window, fg_color="#0F0F0F", corner_radius=0
        )
        self.right_header = ctk.CTkLabel(
            self.right_pane,
            text=" SYSTEM LOG",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#555555",
            anchor="w",
            height=20,
        )
        self.right_header.pack(fill="x", padx=5, pady=(2, 0))

        self.system_edit = ctk.CTkTextbox(
            self.right_pane,
            font=("Consolas", self.console_font_size),
            fg_color="#0F0F0F",
            text_color="#CCCCCC",
            border_width=1,
            border_color="#222222",
            corner_radius=8,
            scrollbar_button_color="#333333",
            scrollbar_button_hover_color="#444444",
            spacing1=5,
            spacing3=5,
        )
        self.system_edit.pack(fill="both", expand=True, padx=5, pady=5)
        self.paned_window.add(self.right_pane, stretch="always")

        # Bind zoom events (Ctrl + Wheel)
        self.text_edit.bind("<Control-MouseWheel>", self._on_zoom)
        self.system_edit.bind("<Control-MouseWheel>", self._on_zoom)

        # Set initial sash position to center (50/50 split) dynamically
        self.after(200, self._initialize_sash)

        self.text_edit.configure(state="disabled")
        self.system_edit.configure(state="disabled")

    def _on_zoom(self, event):
        # Calculate new size (Windows: event.delta is +/- 120)
        if event.delta > 0:
            self.console_font_size = min(self.console_font_size + 1, 30)
        else:
            self.console_font_size = max(self.console_font_size - 1, 6)

        # Apply to both
        new_font = ("Consolas", self.console_font_size)
        self.text_edit.configure(font=new_font)
        self.system_edit.configure(font=new_font)
        return "break"  # Prevents default scrolling behavior if Ctrl is held

    def _initialize_sash(self):
        self.paned_window.update_idletasks()
        width = self.paned_window.winfo_width()
        if width > 1:  # check if widget is mapped
            self.paned_window.sash_place(0, width // 2, 0)

    def _choose_path(self, entry_widget: ctk.CTkEntry):

        path = filedialog.askopenfilename(
            title="Select trace file", filetypes=[("All Files", "*")]
        )
        if path:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, path)

    def _on_run(self):
        normal = self.normal_edit.get().strip()
        slow = self.slow_edit.get().strip()
        target_pkg = self.package_edit.get().strip()
        model = self.model_combo.get().strip()

        if not normal or not slow:
            messagebox.showwarning("Missing paths", "Both trace paths must be set.")
            return
        if not target_pkg:
            messagebox.showwarning("Missing package", "Target package must be set.")
            return
        if not model:
            messagebox.showwarning("Missing model", "Model name must be set.")
            return

        self.status_label.configure(text="Analyzing...")
        self.run_button.configure(state="disabled")
        self.text_edit.configure(state="normal")
        self.text_edit.delete("1.0", "end")
        self.text_edit.configure(state="disabled")
        self.system_edit.configure(state="normal")
        self.system_edit.delete("1.0", "end")
        self.system_edit.configure(state="disabled")
        self.realtime_status.configure(text="")  # Clear status on new run

        self.thread = ExecutorThread(
            normal,
            slow,
            target_pkg,
            model,
            executor=self.executor,
            progress_callback=self._append_line,
            token_callback=self._update_token_usage,
            finished_callback=self._on_finished,
        )
        self.thread.start()

    def _append_line(self, line: str, system: bool = False):
        # Route to AI or System based on the system flag
        target = self.system_edit if system else self.text_edit
        self.after(0, lambda: self._append_to_widget(target, line))

    def _on_stdout_write(self, text: str):
        # Handle stdout pieces nicely
        self.after(0, lambda: self._append_raw(self.system_edit, text))

    def _append_raw(self, widget: ctk.CTkTextbox, text: str):
        widget.configure(state="normal")
        widget.insert("end", text)
        widget.see("end")
        widget.configure(state="disabled")

    def _append_to_widget(self, widget: ctk.CTkTextbox, line: str):
        if line.startswith("\r"):
            # Redirect real-time updates to the status label
            self.realtime_status.configure(text=line[1:])
            return

        # Regular message received - clear status and append to log
        self.realtime_status.configure(text="")
        widget.configure(state="normal")
        
        # Check if widget is empty to avoid leading newline
        if widget.get("1.0", "end-1c").strip():
            widget.insert("end", "\n")
            
        widget.insert("end", line)
        widget.see("end")
        widget.configure(state="disabled")

    def _on_finished(self, results: list):
        self.after(
            0,
            lambda: [
                self.status_label.configure(text="Analysis Complete"),
                messagebox.showinfo("Done", "Execution finished. The application must be restarted for a new run."),
            ],
        )

    def _update_token_usage(self, used: int, total: int):
        pct = int(used / total * 100) if total > 0 else 0
        self.token_label.configure(text=f"Tokens: {used:,} / {total:,} ({pct}%)")
        self.token_bar.set(used / total if total > 0 else 0)

    def _on_close(self):
        if self.thread and self.thread.is_alive():
            self.thread.stop()
        
        if self.executor:
            self.executor.stop()

        # Restore stdout
        if hasattr(self, "original_stdout"):
            sys.stdout = self.original_stdout

        self.destroy()


if __name__ == "__main__":
    app = TraceGui()
    app.mainloop()
