import sys
from gui import TraceGui
from PyQt6 import QtWidgets
from detective_api import DetectiveAPI


if __name__ == "__main__":
    detect = DetectiveAPI

    # if TraceGui is not None:
    #     app = QtWidgets.QApplication(sys.argv)
    #     window = TraceGui()
    #     window.show()
    #     sys.exit(app.exec())
    # else:
    #     print("GUI 모듈을 불러올 수 없습니다. TraceGui 클래스가 정의되어 있는지 확인하세요.")