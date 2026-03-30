import atexit
import io
import sys
import threading
import time
import tkinter as tk
from io import BytesIO
from pilmoji.source import BaseSource
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
try:
    from PIL import Image, ImageDraw, ImageFont
    from pilmoji import Pilmoji
    HAS_PILMOJI = True
except ImportError:
    HAS_PILMOJI = False

from engine import Engine


class ConsoleRedirector:
    def __init__(self, callback, original_stdout=None):
        self.callback = callback
        self.original_stdout = original_stdout

    def write(self, text):
        if text:
            self.callback(text)
            if self.original_stdout:
                try:
                    self.original_stdout.write(text)
                except UnicodeEncodeError:
                    # Fallback for systems that don't support certain emojis in terminal (like Windows CP949)
                    self.original_stdout.write(text.encode('ascii', 'replace').decode('ascii'))

    def flush(self):
        if self.original_stdout:
            self.original_stdout.flush()


class ExecutorThread(threading.Thread):
    def __init__(
        self,
        engine: Engine = None,
        progress_callback=None,
        token_callback=None,
        finished_callback=None,
        start_m_index=0,
        end_m_index=0,
        model_name=None,
        mode="Fast Analysis",
    ):
        super().__init__(daemon=True)
        self.engine = engine
        self.progress_callback = progress_callback
        self.token_callback = token_callback
        self.finished_callback = finished_callback
        self.start_m_index = start_m_index
        self.end_m_index = end_m_index
        self.model_name = model_name
        self.mode = mode
        self.results: list[str] = []
        atexit.register(self.stop)
        self._stop_event = threading.Event()

    def run(self):
        self.token_used = 0
        self.token_total = 0

        def cb(msg: str, system: bool=False):
            if msg.startswith("\\token_zero"):
                self.token_used = 0
                if self.token_callback:
                    self.token_callback(self.token_used, self.token_total)
            elif msg.startswith("\\token"):
                try:
                    self.token_used += int(msg.replace("\\token", "").strip())
                    if self.token_callback:
                        self.token_callback(self.token_used, self.token_total)
                except ValueError:
                    pass
            else:
                self.results.append(msg)
                if self.progress_callback:
                    self.progress_callback(msg, system)

        try:
            try:
                self.token_total = self.engine.llm_requester.get_context_size()
            except Exception:
                self.token_total = 0
            
            self.engine.run(
                output_callback=cb,
                start_m_index=self.start_m_index,
                end_m_index=self.end_m_index,
                model_name=self.model_name,
                mode=self.mode
            )
        finally:
            pass
        if self.finished_callback:
            self.finished_callback(self.results)

    def stop(self):
        # 낱개 쓰레드 중단 시 Executor를 끄지 않음
        self._stop_event.set()

class LocalTwemojiSource(BaseSource):
    def __init__(self, emoji_dir: str = "./assets"):
        self.emoji_dir = Path(emoji_dir)

    def _to_code(self, emoji: str) -> str:
        codepoints = [f"{ord(c):x}" for c in emoji if ord(c) != 0xfe0f]
        return "-".join(codepoints)

    def get_emoji(self, emoji: str) -> BytesIO | None:  # ← bytes 아니고 BytesIO
        code = self._to_code(emoji)
        path = self.emoji_dir / f"{code}.png"

        if not path.exists():
            # fe0f 포함 버전도 시도
            code_full = "-".join(f"{ord(c):x}" for c in emoji)
            path = self.emoji_dir / f"{code_full}.png"

        if path.exists():
            return BytesIO(path.read_bytes())  # ← 여기가 핵심

        print(f"[MISS] {emoji} → {code}.png")
        return None

    def get_discord_emoji(self, id: int) -> BytesIO | None:
        return None

    def request(self, url: str, **kwargs):
        raise RuntimeError(f"네트워크 차단: {url}")

class CTkPilmojiLabel(ctk.CTkLabel):
    """Render colored emojis using pilmoji inside a CTkLabel (via CTkImage)."""
    def __init__(self, master, font_size=15, font_path="C:\\Windows\\Fonts\\malgunbd.ttf", **kwargs):
        self._font_size = font_size
        self._font_path = font_path
        self._text_color = kwargs.get("text_color", "#D0D0D0")
        self._original_text = kwargs.get("text", "")
        self._source = LocalTwemojiSource()
        # Suppress standard text rendering
        kwargs["text"] = ""
        super().__init__(master, **kwargs)
        
        if self._original_text:
            self.set_text(self._original_text)

    def set_text(self, text: str):
        self._original_text = text
        if not HAS_PILMOJI:
            self.configure(text=text)
            return

        try:
            font = ImageFont.truetype(self._font_path, self._font_size)
        except Exception:
            try:
                font = ImageFont.truetype("C:\\Windows\\Fonts\\malgunbd.ttf", self._font_size)
            except Exception:
                font = ImageFont.load_default()

        # Measurement using dummy image
        dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        with Pilmoji(dummy, source=self._source) as pilmoji:
            w, h = pilmoji.getsize(text, font=font)
            # Add some padding
            w = int(w) + 10
            h = int(h) + 15

        # Render RGBA image with transparent background
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        with Pilmoji(img, source=self._source) as pilmoji:
            # Draw with the exact text_color
            pilmoji.text((0, 5), text, font=font, fill=self._get_current_color())

        # Create and set CTkImage
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
        self.configure(image=ctk_img)

    def _get_current_color(self):
        color = self.cget("text_color")
        return color if color else self._text_color

    def configure(self, **kwargs):
        # Intercept text updates
        if "text" in kwargs:
            text = kwargs.pop("text")
            self.set_text(text)
        super().configure(**kwargs)


class TraceGui(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Trace Analyzer")
        self.geometry("1400x800")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Output Redirection (Redirect print() to System Log & Terminal)
        self.original_stdout = sys.stdout
        sys.stdout = ConsoleRedirector(self._on_stdout_write, self.original_stdout)

        # Theme & Appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue") # Keep blue theme but customize colors below

        self.thread: ExecutorThread | None = None
        self.engine = Engine(gui=self)
        self.console_font_size = 12
        self.range_data = []

        # Configure Grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_ui()

        # 프로그램 시작 시 AI 엔진 및 리소스 매니저 초기화 (딱 한 번)
        if hasattr(self, 'status_label'):
            self.status_label.configure(text="⚙️ Initializing System...")
        threading.Thread(target=self._initialize_executor, daemon=True).start()

    def _initialize_executor(self):
        # Disable all inputs during startup
        self.after(0, lambda: self._set_sidebar_state("disabled"))
        
        time.sleep(3)

        self.engine.start(
            output_callback=self._append_line,
            range_callback=self.set_range_data
        )

        self.after(0, lambda: self.status_label.configure(text="✅ System Ready"))
        self.after(0, lambda: self._set_sidebar_state("normal"))

    def _set_sidebar_state(self, state: str):
        """Enable or disable sidebar configuration controls."""
        widgets = [
            self.package_edit, self.client_combo, self.model_combo, self.api_key_edit,
            self.btn_load_data, self.mode_combo, self.normal_edit, self.btn_n,
            self.slow_edit, self.btn_s, self.btn_restart
        ]
        for w in widgets:
            try:
                w.configure(state=state)
            except:
                pass

    def _build_ui(self):
        # --- Sidebar ---
        self.sidebar_frame = ctk.CTkScrollableFrame(
            self, width=280, corner_radius=0, fg_color="#010409",
            scrollbar_button_color="#21262D",
            scrollbar_button_hover_color="#30363D"
        )
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_columnconfigure(0, weight=1)

        # Trace Settings Group
        self.settings_label = CTkPilmojiLabel(
            self.sidebar_frame,
            text="⚙️ CONFIGURATION",
            font_size=13,
            text_color="#FFFFFF",
            anchor="w",
        )
        self.settings_label.grid(row=0, column=0, padx=25, pady=(40, 10), sticky="ew")

        self.package_edit = ctk.CTkEntry(
            self.sidebar_frame,
            placeholder_text="Target package",
            height=40,
            border_width=0,
            fg_color="#0D1117",
            corner_radius=4,
            font=ctk.CTkFont(weight="bold")
        )
        self.package_edit.insert(0, "com.sec.android.gallery3d")
        self.package_edit.grid(row=1, column=0, padx=25, pady=10, sticky="ew")

        self.client_label = CTkPilmojiLabel(
            self.sidebar_frame,
            text="📡 AI CLIENT",
            font_size=12,
            text_color="#94A3B8",
            anchor="w",
        )
        self.client_label.grid(row=2, column=0, padx=25, pady=(20, 0), sticky="ew")

        self.client_combo = ctk.CTkOptionMenu(
            self.sidebar_frame,
            values=["google_studio", "ollama"],
            height=40,
            command=self._on_client_change,
            fg_color="#21262D",
            button_color="#30363D",
            button_hover_color="#3D444D",
            corner_radius=4,
            font=ctk.CTkFont(weight="bold"),
            dropdown_font=ctk.CTkFont(weight="bold")
        )
        self.client_combo.set("google_studio")
        self.client_combo.grid(row=3, column=0, padx=25, pady=(0, 10), sticky="ew")

        self.model_label = CTkPilmojiLabel(
            self.sidebar_frame,
            text="🤖 AI MODEL",
            font_size=12,
            text_color="#94A3B8",
            anchor="w",
        )
        self.model_label.grid(row=4, column=0, padx=25, pady=(5, 0), sticky="ew")

        self.model_combo = ctk.CTkOptionMenu(
            self.sidebar_frame,
            values=["empty"],
            height=40,
            fg_color="#21262D",
            button_color="#30363D",
            button_hover_color="#3D444D",
            corner_radius=4,
            font=ctk.CTkFont(weight="bold"),
            dropdown_font=ctk.CTkFont(weight="bold")
        )
        self.model_combo.set("model")
        self.model_combo.grid(row=5, column=0, padx=25, pady=(0, 10), sticky="ew")

        self.api_key_label = CTkPilmojiLabel(
            self.sidebar_frame,
            text="🔑 API KEY",
            font_size=12,
            text_color="#94A3B8",
            anchor="w",
        )
        self.api_key_label.grid(row=6, column=0, padx=25, pady=(5, 0), sticky="ew")

        self.api_key_edit = ctk.CTkEntry(
            self.sidebar_frame,
            placeholder_text="Enter API Key",
            height=40,
            border_width=0,
            fg_color="#0D1117",
            corner_radius=4,
            font=ctk.CTkFont(family="Consolas", size=12),
            show="*"
        )
        self.api_key_edit.grid(row=7, column=0, padx=25, pady=(0, 15), sticky="ew")

        # Load Data Button
        self.btn_load_data = ctk.CTkButton(
            self.sidebar_frame,
            text="LOAD TRACE DATA",
            command=self._on_load_data,
            height=42,
            fg_color="#21262D",
            hover_color="#30363D",
            corner_radius=4,
            border_width=0,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.btn_load_data.grid(row=8, column=0, padx=25, pady=(20, 10), sticky="ew")

        # Range Selection
        self.range_label = CTkPilmojiLabel(
            self.sidebar_frame,
            text="📏 SCAN RANGE",
            font_size=12,
            text_color="#94A3B8",
            anchor="w",
        )
        self.range_label.grid(row=9, column=0, padx=25, pady=(15, 0), sticky="ew")

        self.range_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.range_frame.grid(row=10, column=0, padx=25, pady=(5, 10), sticky="ew")
        self.range_frame.grid_columnconfigure(0, weight=1)

        self.start_slider = ctk.CTkSlider(
            self.range_frame, from_=0, to=100, height=16,
            command=self._on_range_change,
            progress_color="#4285F4",
            button_color="#E6EDF3",
            button_hover_color="#FFFFFF",
            state="disabled"
        )
        self.start_slider.set(0)
        self.start_slider.grid(row=0, column=0, sticky="ew", pady=(5, 0))
        self.start_val_label = ctk.CTkLabel(
            self.range_frame, text="Start: -", font=ctk.CTkFont(family="Segoe UI Emoji", size=11, weight="bold"), text_color="#A0A0A0", anchor="w"
        )
        self.start_val_label.grid(row=1, column=0, sticky="ew", pady=(0, 5))

        self.end_slider = ctk.CTkSlider(
            self.range_frame, from_=0, to=100, height=16,
            command=self._on_range_change,
            progress_color="#4285F4",
            button_color="#E6EDF3",
            button_hover_color="#FFFFFF",
            state="disabled"
        )
        self.end_slider.set(100)
        self.end_slider.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        self.end_val_label = ctk.CTkLabel(
            self.range_frame, text="End: -", font=ctk.CTkFont(family="Segoe UI Emoji", size=11, weight="bold"), text_color="#A0A0A0", anchor="w"
        )
        self.end_val_label.grid(row=3, column=0, sticky="ew")

        # Analysis Mode Selection
        self.mode_label = CTkPilmojiLabel(
            self.sidebar_frame,
            text="🔍 ANALYSIS MODE",
            font_size=12,
            text_color="#94A3B8",
            anchor="w",
        )
        self.mode_label.grid(row=11, column=0, padx=25, pady=(15, 0), sticky="ew")

        self.mode_combo = ctk.CTkOptionMenu(
            self.sidebar_frame,
            values=["Fast Analysis", "Deep Analysis"],
            height=40,
            fg_color="#21262D",
            button_color="#30363D",
            button_hover_color="#3D444D",
            corner_radius=4,
            font=ctk.CTkFont(weight="bold"),
            dropdown_font=ctk.CTkFont(weight="bold")
        )
        self.mode_combo.set("Fast Analysis")
        self.mode_combo.grid(row=12, column=0, padx=25, pady=(0, 10), sticky="ew")

        # Separator-like padding
        self.path_label = CTkPilmojiLabel(
            self.sidebar_frame,
            text="📂 RESOURCES",
            font_size=13,
            text_color="#FFFFFF",
            anchor="w",
        )
        self.path_label.grid(row=13, column=0, padx=25, pady=(20, 10), sticky="ew")

        # Path Selection
        self.path_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.path_frame.grid(row=14, column=0, padx=25, pady=10, sticky="ew")
        self.path_frame.grid_columnconfigure(0, weight=1)

        self.normal_edit = ctk.CTkEntry(
            self.path_frame,
            placeholder_text="Normal trace path",
            height=35,
            fg_color="#0D1117",
            border_width=0,
            corner_radius=4,
            font=ctk.CTkFont(weight="bold")
        )
        self.normal_edit.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.btn_n = ctk.CTkButton(
            self.path_frame,
            text="Browse Normal",
            command=lambda: self._choose_path(self.normal_edit),
            height=32,
            fg_color="#21262D",
            border_width=0,
            hover_color="#30363D",
            text_color="#8B949E",
            corner_radius=4,
            font=ctk.CTkFont(weight="bold")
        )
        self.btn_n.grid(row=1, column=0, sticky="ew", pady=(0, 20))

        self.slow_edit = ctk.CTkEntry(
            self.path_frame,
            placeholder_text="Slow trace path",
            height=35,
            fg_color="#0D1117",
            border_width=0,
            corner_radius=4,
            font=ctk.CTkFont(weight="bold")
        )
        self.slow_edit.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        self.btn_s = ctk.CTkButton(
            self.path_frame,
            text="Browse Slow",
            command=lambda: self._choose_path(self.slow_edit),
            height=32,
            fg_color="#21262D",
            border_width=0,
            hover_color="#30363D",
            text_color="#8B949E",
            corner_radius=4,
            font=ctk.CTkFont(weight="bold")
        )
        self.btn_s.grid(row=3, column=0, sticky="ew")

        # Restart Button at the bottom
        self.btn_restart = ctk.CTkButton(
            self.sidebar_frame,
            text="🔄 RESTART SYSTEM",
            command=self._on_restart,
            height=40,
            fg_color="#0D1117",
            hover_color="#1F242B",
            corner_radius=4,
            border_width=1,
            border_color="#30363D",
            text_color="#F85149",
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.btn_restart.grid(row=100, column=0, padx=25, pady=(100, 20), sticky="ew")

        # --- Main Content ---
        self.main_container = ctk.CTkFrame(self, corner_radius=0, fg_color="#0D1117")
        self.main_container.grid(row=0, column=1, sticky="nsew")
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(3, weight=1)  # Console row should expand
        self.main_container.grid_rowconfigure(0, weight=0)
        self.main_container.grid_rowconfigure(1, weight=0)
        self.main_container.grid_rowconfigure(2, weight=0)

        # Header with Run Button
        self.header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=30, pady=(30, 20))
        self.header_frame.grid_columnconfigure(0, weight=1)

        self.status_label = CTkPilmojiLabel(
            self.header_frame,
            text="💤 System Standby",
            font_size=26,
            text_color="#FFFFFF"
        )
        self.status_label.grid(row=0, column=0, sticky="w")

        self.run_button = ctk.CTkButton(
            self.header_frame,
            text="INITIALIZE ANALYSIS",
            command=self._on_run,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=45,
            width=200,
            fg_color="#21262D",
            hover_color="#30363D",
            corner_radius=4,
            state="disabled"
        )
        self.run_button.grid(row=0, column=1, sticky="e")

        # Stats Card
        self.stats_frame = ctk.CTkFrame(
            self.main_container,
            corner_radius=8,
            fg_color="#161B22",
            border_width=0,
        )
        self.stats_frame.grid(row=1, column=0, sticky="ew", pady=(0, 30), padx=30)
        self.stats_frame.grid_columnconfigure(0, weight=1)

        self.token_info_frame = ctk.CTkFrame(self.stats_frame, fg_color="transparent")
        self.token_info_frame.pack(fill="x", padx=25, pady=(20, 10))

        self.token_label = ctk.CTkLabel(
            self.token_info_frame,
            text="Tokens: 0 / 0 (0%)",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#94A3B8",
        )
        self.token_label.pack(side="left")

        self.token_bar = ctk.CTkProgressBar(
            self.stats_frame, height=8, progress_color="#4285F4", fg_color="#21262D"
        )
        self.token_bar.set(0)
        self.token_bar.pack(fill="x", padx=25, pady=(0, 20))

        # Real-time Status View (Spinner)
        self.realtime_status = ctk.CTkLabel(
            self.main_container,
            text="",
            font=ctk.CTkFont(family="Consolas", size=16, weight="bold"),
            text_color="#569CD6",
            anchor="w",
            height=25,
        )
        self.realtime_status.grid(row=2, column=0, sticky="ew", padx=35, pady=(0, 2))

        # Console / Terminal View (Split)
        self.console_frame = ctk.CTkFrame(
            self.main_container,
            corner_radius=8,
            fg_color="#0D1117",
            border_width=0,
        )
        self.console_frame.grid(row=3, column=0, sticky="nsew", padx=30, pady=(0, 30))
        self.console_frame.grid_rowconfigure(0, weight=1)
        self.console_frame.grid_columnconfigure(0, weight=1)

        # PanedWindow for split view
        self.paned_window = tk.PanedWindow(
            self.console_frame,
            orient=tk.HORIZONTAL,
            bg="#0D1117",      # Match Dark Graphite background
            sashwidth=4,       # Slightly wider sash for better grab
            sashpad=0,
            bd=0,
            sashrelief=tk.FLAT,
            borderwidth=0
        )
        self.paned_window.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        # Left Pane: AI
        self.left_pane = ctk.CTkFrame(
            self.paned_window, fg_color="#0D1117", corner_radius=0
        )
        self.left_header = CTkPilmojiLabel(
            self.left_pane,
            text=" 🤖 AI INVESTIGATOR",
            font_size=14,
            text_color="#4285F4",
            anchor="w",
            height=20,
        )
        self.left_header.pack(fill="x", padx=5, pady=(2, 0))

        self.text_edit = ctk.CTkTextbox(
            self.left_pane,
            font=("Segoe UI Emoji", self.console_font_size),
            fg_color="#010409",
            text_color="#E6EDF3",
            border_width=0,
            corner_radius=4,
            scrollbar_button_color="#21262D",
            scrollbar_button_hover_color="#30363D",
            spacing1=5,
            spacing3=5,
        )
        self.text_edit.pack(fill="both", expand=True, padx=5, pady=5)
        self.paned_window.add(self.left_pane, stretch="always")

        # Right Pane: System
        self.right_pane = ctk.CTkFrame(
            self.paned_window, fg_color="#0D1117", corner_radius=0
        )
        self.right_header = CTkPilmojiLabel(
            self.right_pane,
            text=" 💻 SYSTEM LOG",
            font_size=14,
            text_color="#94A3B8",
            anchor="w",
            height=20,
        )
        self.right_header.pack(fill="x", padx=5, pady=(2, 0))

        self.system_edit = ctk.CTkTextbox(
            self.right_pane,
            font=("Segoe UI Emoji", self.console_font_size),
            fg_color="#010409",
            text_color="#94A3B8",
            border_width=0,
            corner_radius=4,
            scrollbar_button_color="#21262D",
            scrollbar_button_hover_color="#30363D",
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
        new_font = ("Segoe UI Emoji", self.console_font_size)
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

    def _on_range_change(self, value):
        if not self.range_data:
            return
        
        start_idx = int(self.start_slider.get())
        end_idx = int(self.end_slider.get())
        
        # Ensure indices are within bounds
        start_idx = max(0, min(start_idx, len(self.range_data) - 1))
        end_idx = max(0, min(end_idx, len(self.range_data) - 1))
        
        self.start_val_label.configure(text=f"Start: {self.range_data[start_idx]}")
        self.end_val_label.configure(text=f"End: {self.range_data[end_idx]}")

    def set_range_data(self, data: list[str]):
        """Updates the slider range and data points based on the provided list of strings."""
        self.range_data = data
        if not data:
            self.start_slider.configure(from_=0, to=100, number_of_steps=100)
            self.end_slider.configure(from_=0, to=100, number_of_steps=100)
            self.start_val_label.configure(text="Start: -")
            self.end_val_label.configure(text="End: -")
            return
            
        max_idx = len(data) - 1
        # Set number of steps to max_idx to ensure snaps to whole numbers (indices)
        self.start_slider.configure(from_=0, to=max_idx, number_of_steps=max_idx if max_idx > 0 else 1)
        self.end_slider.configure(from_=0, to=max_idx, number_of_steps=max_idx if max_idx > 0 else 1)
        
        self.start_slider.set(0)
        self.end_slider.set(max_idx)
        self._on_range_change(None)

    def _on_load_data(self):
        """Handle trace data loading in a background thread and enable analysis controls."""
        normal = self.normal_edit.get().strip()
        slow = self.slow_edit.get().strip()
        target_pkg = self.package_edit.get().strip()
        client_type = self.client_combo.get().strip()
        model = self.model_combo.get().strip()
        api_key = self.api_key_edit.get().strip()
        mode = self.mode_combo.get().strip()

        if not normal or not slow:
            messagebox.showwarning("Missing paths", "Both trace paths must be set.")
            return
        if not target_pkg:
            messagebox.showwarning("Missing package", "Target package must be set.")
            return
        if not client_type:
             messagebox.showwarning("Missing Client", "AI Client must be selected.")
             return
        if not model:
            messagebox.showwarning("Missing model", "Model name must be set.")
            return
        if not api_key and client_type == "google_studio":
             messagebox.showwarning("Missing API Key", "Google Studio requires an API Key.")
             return

        # Disable button and show loading status
        self.btn_load_data.configure(state="disabled")
        self.status_label.configure(text="⏳ Loading Data...")

        def load_task():
            nonlocal model
            try:
                # AI 클라이언트 초기화 및 설치된 모델 목록 가져와서 콤보박스 업데이트
                try:
                    self.engine.llm_requester.init_client(client_type)
                    if api_key:
                        self.engine.llm_requester.set_api_key(api_key)
                    
                    models = self.engine.llm_requester.get_installed_models()
                    if models:
                        self.after(0, lambda m=models: self.model_combo.configure(values=m))
                        # 현재 선택된 모델이 목록에 없거나 기본값이면 첫 번째 모델 선택
                        if model == "model" or model not in models:
                            model = models[0]
                            self.after(0, lambda m=model: self.model_combo.set(m))
                except Exception as e:
                    print(f"⚠️ 모델 목록 업데이트 실패: {e}")

                # Call engine.load to initialize data and servers
                self.engine.load(normal, slow, target_pkg, client_type=client_type, api_key=api_key)
                
                # Update GUI on the main thread after successful load
                self.after(0, self._on_load_success)
            except Exception as e:
                # Update GUI on the main thread after error
                self.after(0, lambda: self._on_load_error(e))

        threading.Thread(target=load_task, daemon=True).start()

    def _on_load_success(self):
        """Callback for successful data loading."""
        self.btn_load_data.configure(state="disabled")
        self.run_button.configure(state="normal")
        self.start_slider.configure(state="normal")
        self.end_slider.configure(state="normal")
        
        # Disable configuration inputs but keep model and mode enabled for selection
        self.package_edit.configure(state="disabled")
        self.client_combo.configure(state="disabled")
        self.api_key_edit.configure(state="disabled")
        self.normal_edit.configure(state="disabled")
        self.btn_n.configure(state="disabled")
        self.slow_edit.configure(state="disabled")
        self.btn_s.configure(state="disabled")
        
        # Explicitly enable model and mode for selection after load
        self.model_combo.configure(state="normal")
        self.mode_combo.configure(state="normal")
        
        self.status_label.configure(text="📦 Data Loaded - Ready")
        messagebox.showinfo("Load Data", f"Trace data loaded successfully. Analysis tools are now enabled.\n\nSettings are locked for this session. Use 'RESTART SYSTEM' to load different traces.")

    def _on_load_error(self, error):
        """Callback for failed data loading."""
        self.btn_load_data.configure(state="normal")
        self.status_label.configure(text="⚠️ System Standby")
        messagebox.showerror("Load Error", f"Failed to load trace data: {error}")
        print(f"System Error: Failed to load data - {error}")

    def _on_run(self):
        self.status_label.configure(text="🧠 Analyzing...")
        
        # Disable all UI controls in sidebar and header
        self.run_button.configure(state="disabled")
        self.btn_load_data.configure(state="disabled")
        self.package_edit.configure(state="disabled")
        self.client_combo.configure(state="disabled")
        self.model_combo.configure(state="disabled")
        self.api_key_edit.configure(state="disabled")
        self.mode_combo.configure(state="disabled")
        self.start_slider.configure(state="disabled")
        self.end_slider.configure(state="disabled")
        self.normal_edit.configure(state="disabled")
        self.btn_n.configure(state="disabled")
        self.slow_edit.configure(state="disabled")
        self.btn_s.configure(state="disabled")
        self.btn_restart.configure(state="disabled")

        # Preserve existing logs and add a separator if not empty
        for widget, title in [(self.text_edit, "AI ANALYSIS SESSION"), (self.system_edit, "SYSTEM LOG SESSION")]:
            widget.configure(state="normal")
            if widget.get("1.0", "end-1c").strip():
                separator = f"\n\n{'='*15} 🧠 {title} ({time.strftime('%H:%M:%S')}) {'='*15}\n\n"
                widget.insert("end", separator)
            widget.configure(state="disabled")

        self.realtime_status.configure(text="")  # Clear status on new run

        model = self.model_combo.get().strip()
        mode = self.mode_combo.get().strip()

        self.thread = ExecutorThread(
            engine=self.engine,
            progress_callback=self._append_line,
            token_callback=self._update_token_usage,
            finished_callback=self._on_finished,
            start_m_index=int(self.start_slider.get()),
            end_m_index=int(self.end_slider.get()),
            model_name=model,
            mode=mode,
        )
        self.thread.start()

    def _on_client_change(self, client_type):
        """Update the client and reset model list."""
        try:
            self.engine.llm_requester.init_client(client_type)
            # 클라이언트 바뀔 때 모델 목록 초기화
            self.model_combo.configure(values=["empty"])
            self.model_combo.set("model")
            
            # Key show/hide depending on client
            if client_type == "ollama":
                self.api_key_edit.configure(state="disabled", fg_color="#21262D")
                self.api_key_label.configure(text_color="#4B5563")
            else:
                self.api_key_edit.configure(state="normal", fg_color="#0D1117")
                self.api_key_label.configure(text_color="#94A3B8")
                
        except Exception as e:
            print(f"⚠️ 클라이언트 전환 중 오류: {e}")

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
        def finalize():
            self.status_label.configure(text="🏁 Analysis Complete")
            
            # Re-enable analysis and selection controls (Config remains locked)
            self.run_button.configure(state="normal")
            self.start_slider.configure(state="normal")
            self.end_slider.configure(state="normal")
            self.model_combo.configure(state="normal")
            self.mode_combo.configure(state="normal")
            self.btn_restart.configure(state="normal")
            
            messagebox.showinfo("Done", "Analysis finished. Logs have been preserved. You can run another analysis or load new data.")

        self.after(0, finalize)

    def _update_token_usage(self, used: int, total: int):
        pct = int(used / total * 100) if total > 0 else 0
        self.token_label.configure(text=f"Tokens: {used:,} / {total:,} ({pct}%)")
        self.token_bar.set(used / total if total > 0 else 0)

    def _on_restart(self):
        if not messagebox.askyesno("Restart", "Restart the application? All current session data will be cleared."):
            return
            
        self.status_label.configure(text="♻️ Restarting...")
        self.update()

        # Perform full cleanup
        if self.thread and self.thread.is_alive():
            self.thread.stop()
        
        if self.engine:
            self.engine.stop()

        if hasattr(self, "original_stdout"):
            sys.stdout = self.original_stdout

        import os
        import subprocess
        
        # Launch new process
        subprocess.Popen([sys.executable] + sys.argv)
        
        # Close current process
        self.destroy()
        sys.exit()

    def _on_close(self):
        if self.thread and self.thread.is_alive():
            self.thread.stop()
        
        if self.engine:
            self.engine.stop()

        # Restore stdout
        if hasattr(self, "original_stdout"):
            sys.stdout = self.original_stdout

        self.destroy()


if __name__ == "__main__":
    app = TraceGui()
    app.mainloop()
