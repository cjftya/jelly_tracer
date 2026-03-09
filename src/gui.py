import atexit
import sys

from PyQt6 import QtCore, QtGui, QtWidgets

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
            if msg.startswith("\\token"):
                self.token_used += int(msg.replace("\\token", "").strip())
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


class TraceGui(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        # create a simple magnifier emoji icon for the window
        try:
            pix = QtGui.QPixmap(64, 64)
            pix.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(pix)
            font = QtGui.QFont()
            font.setPointSize(48)
            painter.setFont(font)
            painter.drawText(pix.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "🔍")
            painter.end()
            self.setWindowIcon(QtGui.QIcon(pix))
        except Exception:
            # fallback: ignore if painting fails
            pass

        self.setWindowTitle("LLM Tracer")
        self.resize(800, 600)
        # central widget holds the main layout
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        self.thread: ExecutorThread | None = None

        self._build_ui(central)
        # animate progress bar value changes (token_bar now exists)
        self.token_animation = QtCore.QPropertyAnimation()
        self.token_animation.setTargetObject(self.token_bar)
        self.token_animation.setPropertyName(b"value")
        self.token_animation.setDuration(300)  # milliseconds
        # menus not needed
        self._apply_styles()

    def _build_ui(self, parent: QtWidgets.QWidget):
        # top-level vertical layout
        layout = QtWidgets.QVBoxLayout(parent)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # --- input section ----------------------------------------------------------------
        inputs = QtWidgets.QGroupBox("Trace Settings")
        inputs_layout = QtWidgets.QFormLayout()
        inputs_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        self.package_edit = QtWidgets.QLineEdit()
        self.package_edit.setText("com.sec.android.gallery3d")
        inputs_layout.addRow("Target package:", self.package_edit)

        self.model_edit = QtWidgets.QLineEdit()
        self.model_edit.setPlaceholderText("e.g. gemma3-12b")
        inputs_layout.addRow("Model name:", self.model_edit)

        self.normal_edit = QtWidgets.QLineEdit()
        self.slow_edit = QtWidgets.QLineEdit()
        btn_n = QtWidgets.QPushButton(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirOpenIcon),
            "Browse…",
        )
        btn_n.clicked.connect(lambda: self._choose_path(self.normal_edit))
        btn_s = QtWidgets.QPushButton(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirOpenIcon),
            "Browse…",
        )
        btn_s.clicked.connect(lambda: self._choose_path(self.slow_edit))
        h_n = QtWidgets.QHBoxLayout()
        h_n.addWidget(self.normal_edit)
        h_n.addWidget(btn_n)
        h_s = QtWidgets.QHBoxLayout()
        h_s.addWidget(self.slow_edit)
        h_s.addWidget(btn_s)
        inputs_layout.addRow("Normal trace:", h_n)
        inputs_layout.addRow("Slow trace:", h_s)

        inputs.setLayout(inputs_layout)
        layout.addWidget(inputs)

        # --- controls ---------------------------------------------------------------------
        # analyze button uses only text (emoji included)
        self.run_button = QtWidgets.QPushButton("🔍 Analyze")
        self.run_button.clicked.connect(self._on_run)
        self.run_button.setFixedHeight(40)
        self.run_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(self.run_button)

        # --- progress / tokens -------------------------------------------------------------
        token_box = QtWidgets.QHBoxLayout()
        self.token_label = QtWidgets.QLabel("Tokens: 0 / 0 (0%)")
        token_box.addWidget(self.token_label)
        token_box.addStretch(1)
        layout.addLayout(token_box)

        self.token_bar = QtWidgets.QProgressBar()
        self.token_bar.setMinimum(0)
        self.token_bar.setMaximum(1)
        self.token_bar.setTextVisible(False)
        # make the bar slimmer and more modern-looking
        self.token_bar.setFixedHeight(8)
        self.token_bar.setStyleSheet(
            "QProgressBar {border: 1px solid #aaa; border-radius: 4px; background: #eee;} QProgressBar::chunk {background: #007acc; border-radius: 4px;}"
        )
        layout.addWidget(self.token_bar)

        # --- results ----------------------------------------------------------------------
        result_box = QtWidgets.QGroupBox("Output")
        result_layout = QtWidgets.QVBoxLayout()
        self.text_edit = QtWidgets.QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.WidgetWidth)
        result_layout.addWidget(self.text_edit)
        result_box.setLayout(result_layout)
        layout.addWidget(result_box)

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

        self.text_edit.clear()
        self.run_button.setEnabled(False)
        self.thread = ExecutorThread(normal, slow, target_pkg, model)
        self.thread.progress.connect(self._append_line)
        self.thread.token_progress.connect(self._update_token_usage)
        self.thread.finished.connect(self._on_finished)
        self.thread.start()

    def _append_line(self, line: str):
        # spinner updates: replace last line if starts with \r
        if line.startswith("\r"):
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
            # remove previous block (up to newline)
            cursor.select(QtGui.QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.insertText(line[1:])
        else:
            # append full string preserving newlines
            self.text_edit.append(line)
            # ensure scroll
            self.text_edit.verticalScrollBar().setValue(
                self.text_edit.verticalScrollBar().maximum()
            )

    def _on_finished(self, results: list):
        self.run_button.setEnabled(True)
        QtWidgets.QMessageBox.information(self, "Done", "Execution finished.")

    def _update_token_usage(self, used: int, total: int):
        pct = int(used / total * 100) if total > 0 else 0
        self.token_label.setText(f"Tokens: {used:,} / {total:,} ({pct}%)")
        self.token_bar.setMaximum(total)
        # animate to new value
        self.token_animation.stop()
        self.token_animation.setStartValue(self.token_bar.value())
        self.token_animation.setEndValue(used)
        self.token_animation.start()

    # helpers for styling only

    def _apply_styles(self):
        # use a clean fusion style and light coloring
        QtWidgets.QApplication.setStyle("Fusion")
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(245, 245, 245))
        palette.setColor(
            QtGui.QPalette.ColorRole.WindowText, QtCore.Qt.GlobalColor.black
        )
        palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(255, 255, 255))
        palette.setColor(
            QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor(240, 240, 240)
        )
        palette.setColor(
            QtGui.QPalette.ColorRole.ToolTipBase, QtCore.Qt.GlobalColor.black
        )
        palette.setColor(
            QtGui.QPalette.ColorRole.ToolTipText, QtCore.Qt.GlobalColor.white
        )
        palette.setColor(QtGui.QPalette.ColorRole.Text, QtCore.Qt.GlobalColor.black)
        palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(220, 220, 220))
        palette.setColor(
            QtGui.QPalette.ColorRole.ButtonText, QtCore.Qt.GlobalColor.black
        )
        palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(0, 120, 215))
        palette.setColor(
            QtGui.QPalette.ColorRole.HighlightedText, QtCore.Qt.GlobalColor.white
        )
        QtWidgets.QApplication.setPalette(palette)
        # round corners for various widgets
        sheet = """
            QGroupBox { border: 1px solid #888; border-radius: 8px; margin-top: 6px; }
            QGroupBox:title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 3px; }
            QPushButton { border: 1px solid #888; border-radius: 6px; padding: 4px 12px; }
            QPushButton:hover { background-color: #e6f2ff; }
            QLineEdit, QTextEdit { border: 1px solid #bbb; border-radius: 6px; padding: 2px; }
        """
        # apply style sheet via the existing application instance
        app = QtWidgets.QApplication.instance()
        if app:
            app.setStyleSheet(sheet)


if __name__ == "__main__":
    # ensure QApplication is created before styling
    app = QtWidgets.QApplication(sys.argv)
    window = TraceGui()
    window.show()
    sys.exit(app.exec())
