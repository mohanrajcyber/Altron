from __future__ import annotations

import socket
import threading
import time
import webbrowser

import uvicorn

from altron.settings import Settings


def run_app(settings: Settings) -> int:
    host = settings.altron_host
    port = settings.altron_port
    browse_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{browse_host}:{port}/"

    config = uvicorn.Config(
        "altron.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    if not _wait_port(browse_host, port):
        print(f"Core did not bind {url}")
        server.should_exit = True
        return 1

    try:
        import webview

        webview.create_window("ALTRON", url, width=1280, height=820)
        webview.start()
        server.should_exit = True
        return 0
    except Exception:
        webbrowser.open(url)
        print(f"Desktop window unavailable. Opened browser at {url}")
        print("Core is running. Press Ctrl+C to stop.")
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            server.should_exit = True
        return 0


def _wait_port(host: str, port: int, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.35):
                return True
        except OSError:
            time.sleep(0.12)
    return False
