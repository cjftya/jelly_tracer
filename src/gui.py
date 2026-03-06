import atexit
import sys

from PyQt6 import QtCore, QtWidgets

from executor import Executor
from trace_server_manager import TraceServerManager


class ExecutorThread(QtCore.QThread):
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(list)
    token_progress = QtCore.pyqtSignal(int, int)  # used, total

    def __init__(
        self,
        normal_path: str,
        slow_path: str,
        target_package: str = None,
        model_name: str = "gemma3-12b",
    ):
        super().__init__()
        self.normal_path = normal_path
        self.slow_path = slow_path
        self.target_package = target_package
        self.model_name = model_name
        self.results: list[str] = []
        self.server_manager = TraceServerManager()
        atexit.register(self.stop)

    def run(self):
        self.token_used = 0
        self.token_total = 0

        def cb(msg: str):
            if msg.startswith("\token"):
                self.token_used += int(msg.replace("\token", "").strip())
                self.token_progress.emit(self.token_used, self.token_total)
            else:
                self.results.append(msg)
                self.progress.emit(msg)

        self.server_manager.start_servers(self.normal_path, self.slow_path)

        executor = Executor(model_name=self.model_name)
        # grab actual context size from OllamaManager if available
        try:
            self.token_total = executor.ollamaManager.get_context_size()
        except Exception:
            self.token_total = 0
        executor.run(
            self.normal_path,
            self.slow_path,
            self.target_package,
            output_callback=cb,
        )
        self.finished.emit(self.results)

    def stop(self):
        if self.server_manager != None:
            self.server_manager.stop_servers()
        pass


class TraceGui(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LLM Tracer")
        self.resize(600, 400)
        self._build_ui()
        self.thread: ExecutorThread | None = None

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # target package ------------------------------------------------
        form_target = QtWidgets.QFormLayout()
        self.package_edit = QtWidgets.QLineEdit()
        self.package_edit.setText("com.sec.android.gallery3d")
        form_target.addRow("Target Package:", self.package_edit)
        layout.addLayout(form_target)

        # model name ----------------------------------------------------
        form_target = QtWidgets.QFormLayout()
        self.model_edit = QtWidgets.QLineEdit()
        self.model_edit.setPlaceholderText(
            "ollama에 설치된 model name 입력 (예: gemma3-12b)"
        )
        form_target.addRow("Model Name:", self.model_edit)
        layout.addLayout(form_target)

        # path selectors ------------------------------------------------
        form = QtWidgets.QFormLayout()
        self.normal_edit = QtWidgets.QLineEdit()
        self.slow_edit = QtWidgets.QLineEdit()

        btn_n = QtWidgets.QPushButton("Browse…")
        btn_n.clicked.connect(lambda: self._choose_path(self.normal_edit))
        btn_s = QtWidgets.QPushButton("Browse…")
        btn_s.clicked.connect(lambda: self._choose_path(self.slow_edit))

        h_n = QtWidgets.QHBoxLayout()
        h_n.addWidget(self.normal_edit)
        h_n.addWidget(btn_n)

        h_s = QtWidgets.QHBoxLayout()
        h_s.addWidget(self.slow_edit)
        h_s.addWidget(btn_s)

        form.addRow("Normal trace:", h_n)
        form.addRow("Slow trace:", h_s)
        layout.addLayout(form)

        # run button -----------------------------------------------------
        self.run_button = QtWidgets.QPushButton("Run")
        self.run_button.clicked.connect(self._on_run)
        layout.addWidget(self.run_button)

        # token usage text + progress ------------------------------------
        self.token_label = QtWidgets.QLabel("Tokens: 0 / 0 (0%)")
        layout.addWidget(self.token_label)
        self.token_bar = QtWidgets.QProgressBar()
        self.token_bar.setMinimum(0)
        self.token_bar.setMaximum(1)  # will be reset when actual total known
        self.token_bar.setTextVisible(False)
        self.token_bar.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.token_bar)

        # results list --------------------------------------------------
        self.list_widget = QtWidgets.QListWidget()
        layout.addWidget(self.list_widget)

    def _choose_path(self, edit: QtWidgets.QLineEdit):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select trace file", "", "All Files (*)"
        )
        if path:
            edit.setText(path)

    def _on_run(self):
        normal = self.normal_edit.text().strip()
        slow = self.slow_edit.text().strip()
        target_pkg = self.package_edit.text().strip()
        model = self.model_edit.text().strip()
        if not normal or not slow:
            QtWidgets.QMessageBox.warning(
                self, "Missing paths", "Both trace paths must be set."
            )
            return
        if not target_pkg:
            QtWidgets.QMessageBox.warning(
                self, "Missing package", "Target package must be set."
            )
            return
        if not model:
            QtWidgets.QMessageBox.warning(
                self, "Missing model", "Model name must be set."
            )
            return

        self.list_widget.clear()
        self.run_button.setEnabled(False)
        self.thread = ExecutorThread(normal, slow, target_pkg, model)
        self.thread.progress.connect(self._append_line)
        self.thread.token_progress.connect(self._update_token_usage)
        self.thread.finished.connect(self._on_finished)
        self.thread.start()

    def _append_line(self, line: str):
        # \r로 시작하면 마지막 항목을 업데이트 (spinner용)
        if line.startswith("\r"):
            if self.list_widget.count() > 0:
                last_item = self.list_widget.item(self.list_widget.count() - 1)
                last_item.setText(line[1:])  # \r 제거
            else:
                self.list_widget.addItem(line[1:])
        else:
            for ln in line.splitlines():
                if ln:
                    self.list_widget.addItem(ln)
                    self.list_widget.scrollToBottom()

    def _on_finished(self, results: list):
        self.run_button.setEnabled(True)
        QtWidgets.QMessageBox.information(self, "Done", "Execution finished.")

    def _update_token_usage(self, used: int, total: int):
        pct = int(used / total * 100) if total > 0 else 0
        self.token_label.setText(f"Tokens: {used:,} / {total:,} ({pct}%)")
        self.token_bar.setMaximum(total)
        self.token_bar.setValue(used)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = TraceGui()
    window.show()
    sys.exit(app.exec())
