from types import ModuleType
from unittest.mock import MagicMock
import importlib
import sys


# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing the module under test
# ---------------------------------------------------------------------------


def _stub_pyside():
    qt_core = ModuleType("PySide6.QtCore")

    class _DummySignal:  # pylint: disable=too-few-public-methods
        def __init__(self, *_, **__):
            pass

        def emit(self, *_, **__):
            pass

        def connect(self, *_, **__):
            pass

    class _Qt:
        ShiftModifier = 0x02000000
        WindowModal = 1

    def _slot(*_args, **_kwargs):  # noqa: ANN001
        def wrapper(func):
            return func

        return wrapper

    class _DummyTimer:
        def __init__(self, *_, **__):
            pass

        def setInterval(self, *_args, **_kwargs):
            pass

        def timeout(self):  # pragma: no cover - placeholder
            return _DummySignal()

        def start(self, *_args, **_kwargs):
            pass

    qt_core.QThread = object
    qt_core.Signal = _DummySignal
    qt_core.Slot = _slot
    qt_core.Qt = _Qt
    qt_core.QTimer = _DummyTimer

    qt_widgets = ModuleType("PySide6.QtWidgets")

    class _DummyWidget:
        def __init__(self, *_, **__):
            pass

    class _DummyDialog(_DummyWidget):
        def setLabelText(self, *_args, **_kwargs):
            pass

    # Populate minimal widget classes referenced in main.py
    for name, cls in {
        "QApplication": _DummyWidget,
        "QCheckBox": _DummyWidget,
        "QComboBox": _DummyWidget,
        "QFormLayout": _DummyWidget,
        "QHBoxLayout": _DummyWidget,
        "QInputDialog": _DummyWidget,
        "QLabel": _DummyWidget,
        "QLineEdit": _DummyWidget,
        "QMessageBox": _DummyWidget,
        "QPushButton": _DummyWidget,
        "QSpinBox": _DummyWidget,
        "QStackedWidget": _DummyWidget,
        "QTextEdit": _DummyWidget,
        "QVBoxLayout": _DummyWidget,
        "QWidget": _DummyWidget,
        "QProgressBar": _DummyWidget,
        "QDialog": _DummyDialog,
        "QProgressDialog": _DummyDialog,
    }.items():
        setattr(qt_widgets, name, cls)

    qt_gui = ModuleType("PySide6.QtGui")
    qt_gui.QIcon = _DummyWidget

    sys.modules["PySide6"] = ModuleType("PySide6")
    sys.modules["PySide6.QtCore"] = qt_core
    sys.modules["PySide6.QtWidgets"] = qt_widgets
    sys.modules["PySide6.QtGui"] = qt_gui


def _stub_aws():
    sys.modules["boto3"] = MagicMock()
    sys.modules["botocore"] = MagicMock()
    sys.modules["botocore.exceptions"] = MagicMock()
    sys.modules["aws_utils"] = MagicMock()
    sys.modules["widgets"] = MagicMock()


_stub_pyside()
_stub_aws()


main = importlib.import_module("aws_deployer_app.main")


def test_format_bytes_scaling():
    assert main.format_bytes(512) == "512.0B"
    assert main.format_bytes(2048) == "2.0KB"
    assert main.format_bytes(5 * 1024**3) == "5.0GB"


def test_format_rate_zero_and_positive():
    assert main.format_rate(0) == "0 B/s"
    assert main.format_rate(1536) == "1.5KB/s"


def test_compose_transfer_label_includes_rate_and_totals():
    text = main.compose_transfer_label("Downloading", 1536, 3072, 1024)
    assert "Downloading…" in text
    assert "1.5KB / 3.0KB" in text
    assert "1.0KB/s" in text


def test_compose_transfer_label_unknown_total():
    text = main.compose_transfer_label("Uploading", 256, 0, 0)
    assert "/ ?" in text
    assert "(0 B/s)" in text

