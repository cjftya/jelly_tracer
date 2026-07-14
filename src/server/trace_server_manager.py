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
        # 1. Proactively clean up any orphaned or running processes before starting new ones
        self.stop_servers()
        
        self.trace_n = trace_n
        self.trace_s = trace_s

        print("🚀 Configuring Trace Analysis Environment...")
        configs = [(9001, self.trace_n), (9002, self.trace_s)]

        for port, trace in configs:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if self.os_type == "Windows":
                exe_path = os.path.join(
                    project_root,
                    "lib",
                    "windows",
                    "trace_processor_shell.exe",
                )
            else:
                exe_path = os.path.join(
                    project_root, "lib", "trace_processor"
                )
                os.chmod(exe_path, 0o755)
            cmd = [exe_path, "--httpd", trace, "--http-port", str(port)]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self.procs.append(proc)

        time.sleep(5)
        print("✅ Complete")

    def stop_servers(self):
        print("🚿 Cleaning up Trace Sessions...")
        if self.procs:
            for proc in self.procs:
                try:
                    proc.terminate()
                except Exception:
                    pass
            self.procs.clear()
        
        try:
            if self.os_type == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "trace_processor_shell.exe", "/T"], 
                    capture_output=True, 
                    text=True
                )
            else:
                subprocess.run(
                    ["pkill", "-f", "trace_processor"],
                    capture_output=True,
                    text=True
                )
        except Exception as e:
            print(f"⚠️ Process cleanup warning: {e}")
        print("✅ Complete")
