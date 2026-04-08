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

        print("🚀 Configuring Trace Analysis Environment...")
        configs = [(9001, self.trace_n), (9002, self.trace_s)]

        for port, trace in configs:
            if self.os_type == "Windows":
                exe_path = os.path.join(
                    os.path.dirname(__file__),
                    "trace_server",
                    "windows",
                    "trace_processor_shell.exe",
                )
            else:
                exe_path = os.path.join(
                    os.path.dirname(__file__), "trace_server", "trace_processor"
                )
                os.chmod(exe_path, 0o755)
            cmd = f"{exe_path} --httpd {trace} --http-port {port}"
            proc = subprocess.Popen(
                cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self.procs.append(proc)

        time.sleep(5)
        print("✅ Complete")

    def export_db(self, db_path):
        def export_to_sqlite(trace_path, db_path):
            exe_path = None
            if self.os_type == "Windows":
                exe_path = os.path.join(
                    os.path.dirname(__file__),
                    "trace_server",
                    "windows",
                    "trace_processor_shell.exe",
                )
            else:
                exe_path = os.path.join(
                    os.path.dirname(__file__), "trace_server", "trace_processor"
                )
                os.chmod(exe_path, 0o755)

            trace_path = os.path.normpath(trace_path)
            trace_name = os.path.basename(trace_path)
            output_db = os.path.normpath(os.path.join(db_path, f"{trace_name}.db"))

            cmd = [
                exe_path, '-e', 
                output_db, trace_path
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                print(f"✅ Success: {output_db} created!")
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed: {trace_name} conversion error!")
                print(f"Error message: {e.stderr}")
            except FileNotFoundError:
                print(f"🚫 Error: {exe_path} file not found!")

        export_to_sqlite(self.trace_n, db_path)
        export_to_sqlite(self.trace_s, db_path)

    def stop_servers(self):
        if self.procs:
            print(f"🚿 Cleaning up Trace Sessions... {len(self.procs)} processes")
            for proc in self.procs:
                proc.terminate()
            
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
            print("✅ Complete")
