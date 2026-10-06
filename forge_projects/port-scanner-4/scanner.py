import socket
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

def is_localhost(host: str) -> bool:
    """Allow only 127.0.0.1 or localhost."""
    return host.strip().lower() in ("127.0.0.1", "localhost")

def scan_ports(host, start_port, end_port, output_widget):
    open_ports = []
    for port in range(start_port, end_port + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                result = s.connect_ex((host, port))
                if result == 0:
                    open_ports.append(port)
                    output_widget.insert(tk.END, f"Port {port}: OPEN\n")
                else:
                    output_widget.insert(tk.END, f"Port {port}: closed\n")
        except Exception as e:
            output_widget.insert(tk.END, f"Port {port}: error ({e})\n")
        output_widget.see(tk.END)
    output_widget.insert(tk.END, f"\nScan complete. Open ports: {open_ports}\n")
    output_widget.see(tk.END)

def start_scan():
    host = host_entry.get().strip()
    if not is_localhost(host):
        messagebox.showerror("Invalid target", "For safety, only 127.0.0.1 or localhost is allowed.")
        return
    try:
        start = int(start_port_entry.get())
        end = int(end_port_entry.get())
        if not (0 < start <= 65535 and 0 < end <= 65535 and start <= end):
            raise ValueError
    except ValueError:
        messagebox.showerror("Invalid range", "Enter valid port numbers (1-65535) with start ≤ end.")
        return
    output_text.delete(1.0, tk.END)
    output_text.insert(tk.END, f"Scanning {host} ports {start}-{end}...\n")
    # Run scan in a simple loop (UI will freeze briefly; acceptable for educational tool)
    scan_ports(host, start, end, output_text)

# UI setup
root = tk.Tk()
root.title("Localhost Port Scanner (Educational)")
root.geometry("500x400")
root.resizable(False, False)

frame = ttk.Frame(root, padding="10")
frame.pack(fill=tk.BOTH, expand=True)

ttk.Label(frame, text="Target (localhost only):").grid(row=0, column=0, sticky="w")
host_entry = ttk.Entry(frame, width=20)
host_entry.grid(row=0, column=1, sticky="w")
host_entry.insert(0, "127.0.0.1")

ttk.Label(frame, text="Start Port:").grid(row=1, column=0, sticky="w")
start_port_entry = ttk.Entry(frame, width=10)
start_port_entry.grid(row=1, column=1, sticky="w")
start_port_entry.insert(0, "1")

ttk.Label(frame, text="End Port:").grid(row=1, column=2, sticky="w")
end_port_entry = ttk.Entry(frame, width=10)
end_port_entry.grid(row=1, column=3, sticky="w")
end_port_entry.insert(0, "1024")

scan_btn = ttk.Button(frame, text="Scan", command=start_scan)
scan_btn.grid(row=2, column=0, columnspan=4, pady=10)

ttk.Label(frame, text="Results:").grid(row=3, column=0, sticky="w")
output_text = scrolledtext.ScrolledText(frame, width=58, height=15, wrap=tk.WORD)
output_text.grid(row=4, column=0, columnspan=4, pady=5)

root.mainloop()
