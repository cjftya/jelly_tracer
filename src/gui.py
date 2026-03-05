from PyQt6 import QtWidgets, QtCore
from executor import Executor
import sys


class ExecutorThread(QtCore.QThread):
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(list)

    def __init__(self, normal_path: str, slow_path: str, target_name: str = None, model_name: str = 'gemma3-12b'):
        super().__init__()
        self.normal_path = normal_path
        self.slow_path = slow_path
        self.target_name = target_name
        self.model_name = model_name
        self.results: list[str] = []

    def run(self):
        # callback will be invoked for every line emitted by the executor
        def cb(msg: str):
            self.results.append(msg)
            self.progress.emit(msg)

        executor = Executor(model_name=self.model_name)
        executor.run(self.normal_path, self.slow_path, output_callback=cb, target_name=self.target_name)
        self.finished.emit(self.results)


class TraceGui(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LLM Tracer")
        self.resize(600, 400)
        self._build_ui()
        self.thread: ExecutorThread | None = None

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # target app name -----------------------------------------------
        form_target = QtWidgets.QFormLayout()
        self.target_edit = QtWidgets.QLineEdit()
        self.target_edit.setText("Gallery(com.sec.android.gallery3d)")
        self.model_edit = QtWidgets.QLineEdit()
        self.model_edit.setPlaceholderText("ollama에 설치된 model name")
        form_target.addRow("Target App:", self.target_edit)
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

        # results list --------------------------------------------------
        self.list_widget = QtWidgets.QListWidget()
        layout.addWidget(self.list_widget)

    def _choose_path(self, edit: QtWidgets.QLineEdit):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select trace file", "", "All Files (*)")
        if path:
            edit.setText(path)

    def _on_run(self):
        normal = self.normal_edit.text().strip()
        slow = self.slow_edit.text().strip()
        target = self.target_edit.text().strip()
        model = self.model_edit.text().strip()
        if not normal or not slow:
            QtWidgets.QMessageBox.warning(self, "Missing paths", "Both trace paths must be set.")
            return
        if not target:
            QtWidgets.QMessageBox.warning(self, "Missing target", "Target app name must be set.")
            return
        if not model:
            QtWidgets.QMessageBox.warning(self, "Missing model", "Model name must be set.")
            return

        self.list_widget.clear()
        self.run_button.setEnabled(False)
        self.thread = ExecutorThread(normal, slow, target, model)
        self.thread.progress.connect(self._append_line)
        self.thread.finished.connect(self._on_finished)
        self.thread.start()

    def _append_line(self, line: str):
        # \r로 시작하면 마지막 항목을 업데이트 (spinner용)
        if line.startswith('\r'):
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


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = TraceGui()
    window.show()
    sys.exit(app.exec())
