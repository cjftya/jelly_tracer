import os
import platform
import subprocess
import time


class TraceServerManager:
    def __init__(self):
        self.trace_n = None
        self.trace_s = None
        self.procs = []
        self.os_type = platform.system()

    def start_servers(self, trace_n, trace_s):
        self.trace_n = trace_n
        self.trace_s = trace_s

        print("🚀 서버 시작 중...")
        configs = [(9001, self.trace_n), (9002, self.trace_s)]

        for port, trace in configs:
            # choose processor executable location depending on OS
            if self.os_type == "Windows":
                exe_path = os.path.join(
                    os.path.dirname(__file__),
                    "trace_server",
                    "windows",
                    "trace_processor_shell.exe",
                )
            else:
                # assume Linux for now; can be extended for Mac if needed
                exe_path = os.path.join(
                    os.path.dirname(__file__), "trace_server", "trace_processor"
                )
            # ensure executable form is correct for subprocess
            cmd = f"{exe_path} --httpd {trace} --http-port {port}"
            proc = subprocess.Popen(
                cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self.procs.append(proc)

        time.sleep(5)
        print("✅ 모든 서버가 대기 중입니다")

    def stop_servers(self):
        print(f"🚿 서버 소켓 반납 중...{len(self.procs)}개")
        for proc in self.procs:
            proc.terminate()
        print("✅ 모든 서버가 안전하게 닫혔습니다")
