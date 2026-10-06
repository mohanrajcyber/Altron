# Localhost Port Scanner (Educational)

A small Python/Tkinter TCP port scanner for local education. It accepts only `127.0.0.1` or `localhost`; other targets are rejected. Keep demonstrations on a computer or lab you control.

## Files
- `port_scanner.py` – main application

## Usage

Requires Python 3.11+ with Tkinter available. No third-party packages are required.

```powershell
python port_scanner.py
```

Enter a port range and choose **Start Scan**. The default range is 1–1024; a single scan is limited to 4096 ports. Open ports are displayed in the results area.

The worker thread performs socket checks only. UI updates are delivered back to Tk's main event loop through a thread-safe queue.

## Validation

ALTRON verified that the Python file parses. The app itself was not executed. The local, non-network guard tests were run after generation: **2 passed**. Rerun them with:

```powershell
python -m pytest tests
```

## Security notes

The UI restricts targets to the literal loopback names `localhost` and `127.0.0.1`. Do not modify that check to scan systems without explicit authorization.
