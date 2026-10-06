import socket
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox


class PortScannerApp:
    MAX_PORT_RANGE = 4096

    def __init__(self, root):
        self.root = root
        self.root.title("Localhost Port Scanner (Educational)")
        self.root.geometry("500x400")
        self.root.resizable(False, False)
        self.messages = queue.Queue()

        # Target frame
        target_frame = ttk.LabelFrame(root, text="Target")
        target_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(target_frame, text="Host:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.host_var = tk.StringVar(value="127.0.0.1")
        host_entry = ttk.Entry(target_frame, textvariable=self.host_var, width=20)
        host_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        # Port range frame
        port_frame = ttk.LabelFrame(root, text="Port Range")
        port_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(port_frame, text="Start Port:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.start_port = tk.IntVar(value=1)
        ttk.Entry(port_frame, textvariable=self.start_port, width=8).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(port_frame, text="End Port:").grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.end_port = tk.IntVar(value=1024)
        ttk.Entry(port_frame, textvariable=self.end_port, width=8).grid(row=0, column=3, padx=5, pady=5, sticky="w")

        # Scan button
        self.scan_btn = ttk.Button(root, text="Start Scan", command=self.start_scan)
        self.scan_btn.pack(pady=10)

        # Results area
        result_frame = ttk.LabelFrame(root, text="Scan Results")
        result_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.result_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD, height=15)
        self.result_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.result_text.config(state=tk.DISABLED)
        self.root.after(100, self.process_messages)

    def validate_target(self, host):
        """Only allow loopback targets for this educational demonstration."""
        return (host or "").strip().lower() in {"127.0.0.1", "localhost"}

    def validate_port_range(self, start, end):
        return 1 <= start <= end <= 65535 and end - start + 1 <= self.MAX_PORT_RANGE

    def scan_port(self, host, port):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False
        finally:
            if sock is not None:
                sock.close()

    def worker(self, host, start, end):
        open_ports = []
        try:
            for port in range(start, end + 1):
                if self.scan_port(host, port):
                    open_ports.append(port)
                    self.messages.put(("open", port))
            self.messages.put(("done", open_ports))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def append_result(self, text):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.insert(tk.END, text)
        self.result_text.see(tk.END)
        self.result_text.config(state=tk.DISABLED)

    def process_messages(self):
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "open":
                    self.append_result(f"Port {value}: OPEN\n")
                elif kind == "done":
                    summary = value if value else "None"
                    self.append_result(f"\nScan complete. Open ports: {summary}\n")
                    self.scan_btn.config(state=tk.NORMAL)
                elif kind == "error":
                    messagebox.showerror("Scan Error", value or "The scan could not be completed.")
                    self.scan_btn.config(state=tk.NORMAL)
        except queue.Empty:
            pass
        self.root.after(100, self.process_messages)

    def start_scan(self):
        host = self.host_var.get().strip()
        try:
            start = self.start_port.get()
            end = self.end_port.get()
        except (tk.TclError, ValueError):
            messagebox.showerror("Invalid Range", "Enter whole-number ports between 1 and 65535.")
            return
        if not self.validate_target(host):
            messagebox.showerror("Invalid Target", "For safety, only localhost (127.0.0.1) is allowed.")
            return
        if not self.validate_port_range(start, end):
            messagebox.showerror(
                "Invalid Range",
                f"Choose ports from 1 to 65535, in ascending order, with no more than {self.MAX_PORT_RANGE} ports.",
            )
            return

        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, f"Scanning {host} ports {start}-{end}...\n")
        self.result_text.config(state=tk.DISABLED)
        self.scan_btn.config(state=tk.DISABLED)
        thread = threading.Thread(target=self.worker, args=(host, start, end), daemon=True)
        thread.start()

if __name__ == "__main__":
    root = tk.Tk()
    app = PortScannerApp(root)
    root.mainloop()
