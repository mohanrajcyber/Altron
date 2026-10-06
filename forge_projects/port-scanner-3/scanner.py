import socket
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from queue import Queue

# -------------------------- Validation --------------------------
def is_localhost(target: str) -> bool:
    """Allow only 127.0.0.1, localhost, or ::1 (IPv6 loopback)."""
    return target.strip().lower() in {"127.0.0.1", "localhost", "::1"}

# -------------------------- Scanner Core --------------------------
def scan_port(target: str, port: int, result_queue: Queue):
    try:
        with socket.create_connection((target, port), timeout=0.5):
            result_queue.put((port, "OPEN"))
    except (socket.timeout, ConnectionRefusedError, OSError):
        result_queue.put((port, "CLOSED"))

def worker(target: str, port_queue: Queue, result_queue: Queue):
    while not port_queue.empty():
        port = port_queue.get()
        scan_port(target, port, result_queue)
        port_queue.task_done()

def start_scan(target: str, start_port: int, end_port: int, output_box: scrolledtext.ScrolledText):
    if not is_localhost(target):
        output_box.insert(tk.END, f"[!] Error: Only localhost (127.0.0.1) is allowed for scanning.\\n")
        output_box.see(tk.END)
        return

    output_box.delete(1.0, tk.END)
    output_box.insert(tk.END, f"[+] Scanning {target} ports {start_port}-{end_port}...\\n")
    output_box.see(tk.END)

    port_queue = Queue()
    result_queue = Queue()
    for p in range(start_port, end_port + 1):
        port_queue.put(p)

    threads = []
    for _ in range(min(100, end_port - start_port + 1)):
        t = threading.Thread(target=worker, args=(target, port_queue, result_queue), daemon=True)
        t.start()
        threads.append(t)

    def poll_results():
        while not result_queue.empty():
            port, state = result_queue.get()
            if state == "OPEN":
                output_box.insert(tk.END, f"[+] Port {port}: OPEN\\n")
        if any(t.is_alive() for t in threads):
            output_box.after(100, poll_results)
        else:
            output_box.insert(tk.END, "[+] Scan complete.\\n")
        output_box.see(tk.END)

    output_box.after(100, poll_results)

# -------------------------- GUI --------------------------
def build_gui():
    root = tk.Tk()
    root.title("Localhost Port Scanner (Educational)")
    root.resizable(False, False)

    mainframe = ttk.Frame(root, padding="10")
    mainframe.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    ttk.Label(mainframe, text="Target (localhost only):").grid(row=0, column=0, sticky=tk.W)
    target_var = tk.StringVar(value="127.0.0.1")
    ttk.Entry(mainframe, width=20, textvariable=target_var).grid(row=0, column=1, sticky=(tk.W, tk.E))

    ttk.Label(mainframe, text="Start Port:").grid(row=1, column=0, sticky=tk.W)
    start_var = tk.IntVar(value=1)
    ttk.Entry(mainframe, width=10, textvariable=start_var).grid(row=1, column=1, sticky=tk.W)

    ttk.Label(mainframe, text="End Port:").grid(row=2, column=0, sticky=tk.W)
    end_var = tk.IntVar(value=1024)
    ttk.Entry(mainframe, width=10, textvariable=end_var).grid(row=2, column=1, sticky=tk.W)

    scan_btn = ttk.Button(mainframe, text="Start Scan")
    scan_btn.grid(row=3, column=0, columnspan=2, pady=8, sticky=(tk.W, tk.E))

    output = scrolledtext.ScrolledText(mainframe, width=50, height=15, wrap=tk.WORD)
    output.grid(row=4, column=0, columnspan=2, pady=5, sticky=(tk.W, tk.E))

    def on_scan():
        scan_btn.state(["disabled"])
        output.delete(1.0, tk.END)
        threading.Thread(
            target=start_scan,
            args=(target_var.get(), start_var.get(), end_var.get(), output),
            daemon=True,
        ).start()
        root.after(100, lambda: scan_btn.state(["!disabled"]))

    scan_btn.config(command=on_scan)

    for child in mainframe.winfo_children():
        child.grid_configure(padx=5, pady=5)

    root.mainloop()

if __name__ == "__main__":
    build_gui()
