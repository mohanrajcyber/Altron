import importlib.util
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "port_scanner.py"
SPEC = importlib.util.spec_from_file_location("port_scanner", APP_PATH)
PORT_SCANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PORT_SCANNER)


def _app_without_ui():
    return PORT_SCANNER.PortScannerApp.__new__(PORT_SCANNER.PortScannerApp)


def test_target_validation_allows_only_loopback_names():
    app = _app_without_ui()
    assert app.validate_target("127.0.0.1")
    assert app.validate_target("LOCALHOST")
    assert not app.validate_target("192.168.1.10")
    assert not app.validate_target("example.com")


def test_port_range_is_ordered_valid_and_bounded():
    app = _app_without_ui()
    assert app.validate_port_range(1, 1024)
    assert app.validate_port_range(1, 4096)
    assert not app.validate_port_range(1, 4097)
    assert not app.validate_port_range(1024, 1)
    assert not app.validate_port_range(0, 20)
    assert not app.validate_port_range(1, 65536)