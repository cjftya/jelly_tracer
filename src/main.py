from gui import TraceGui

if __name__ == "__main__":
    if TraceGui is not None:
        app = TraceGui()
        app.mainloop()
    else:
        print(
            "GUI 모듈을 불러올 수 없습니다. TraceGui 클래스가 정의되어 있는지 확인하세요."
        )
