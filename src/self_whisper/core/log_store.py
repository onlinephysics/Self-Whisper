"""
Self-Whisper Central Log Store
Thread-safe in-memory ring buffer for application logs and dictation history.

Why this exists: the app used to require a visible terminal window so users
could see logs/prints. Now everything is captured here and shown in the
Settings -> Logs tab, so the app can run windowless (pythonw / no console).

Usage:
    from self_whisper.core.log_store import log, log_dictation, get_logs_text, ...
    log("message")               # INFO-level app log (also goes to `logging`)
    log_dictation("আমি ...")     # finalized dictation entry (history section)

Qt integration: `log_hub.new_entry` is a thread-safe pyqtSignal emitted for
every new line, so the Logs tab can append live from any thread.
"""

import collections
import logging
import sys
import threading
import time
from typing import Deque, List, Tuple

try:
    from PyQt6.QtCore import QObject, pyqtSignal

    class _LogHub(QObject):
        new_entry = pyqtSignal(str, str)  # (kind, formatted_line)

    log_hub = _LogHub()
except Exception:  # pragma: no cover - Qt import should always succeed in app
    log_hub = None

_MAX_APP_LINES = 800
_MAX_DICTATION_ENTRIES = 200

_lock = threading.Lock()
_app_lines: Deque[str] = collections.deque(maxlen=_MAX_APP_LINES)
_dictations: Deque[Tuple[str, str]] = collections.deque(maxlen=_MAX_DICTATION_ENTRIES)  # (timestamp, text)

_logger = logging.getLogger("selfwhisper")


def _timestamp() -> str:
    return time.strftime("%H:%M:%S")


def _emit(kind: str, line: str):
    try:
        if log_hub is not None:
            log_hub.new_entry.emit(kind, line)
    except Exception:
        pass


def log(message: str, level: int = logging.INFO):
    """Records an app log line (kept in memory + forwarded to stdlib logging)."""
    line = f"[{_timestamp()}] {message}"
    with _lock:
        _app_lines.append(line)
    try:
        _logger.log(level, message)
    except Exception:
        pass
    _emit("app", line)


def log_dictation(text: str):
    """Records a finalized dictation with timestamp (shown in Logs tab history)."""
    text = (text or "").strip()
    if not text:
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        _dictations.append((ts, text))
    log(f"Dictated: {text}")
    _emit("dictation", f"[{ts}] {text}")


def get_app_lines() -> List[str]:
    with _lock:
        return list(_app_lines)


def get_dictations() -> List[Tuple[str, str]]:
    with _lock:
        return list(_dictations)


def get_logs_text() -> str:
    """Full plain-text dump (dictations first, then app log) for Copy buttons."""
    parts = ["== Dictation history =="]
    for ts, text in get_dictations():
        parts.append(f"[{ts}] {text}")
    parts.append("")
    parts.append("== Application log ==")
    parts.extend(get_app_lines())
    return "\n".join(parts)


def clear_all():
    with _lock:
        _app_lines.clear()
        _dictations.clear()
    _emit("clear", "")


class _TeeStream:
    """Stdout/stderr tee: keeps original stream working AND captures prints.

    Under pythonw there is no console (sys.stdout is None); in that case we
    only capture into the log store.
    """

    def __init__(self, original, tag: str):
        self._original = original
        self._tag = tag
        self._buf_lock = threading.Lock()
        self._partial = ""

    def write(self, data):
        if not data:
            return 0
        try:
            if self._original is not None:
                self._original.write(data)
        except Exception:
            pass
        try:
            text = str(data)
            with self._buf_lock:
                self._partial += text
                while "\n" in self._partial:
                    line, self._partial = self._partial.split("\n", 1)
                    line = line.rstrip("\r")
                    if line.strip():
                        with _lock:
                            _app_lines.append(f"[{_timestamp()}] {line}")
                        _emit("app", f"[{_timestamp()}] {line}")
        except Exception:
            pass
        return len(str(data))

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        try:
            if self._original is not None:
                self._original.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self._original.isatty() if self._original else False
        except Exception:
            return False


class _StoreHandler(logging.Handler):
    """Forwards stdlib logging records into the store (no duplicates)."""

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            for line in str(msg).splitlines():
                if line.strip():
                    with _lock:
                        _app_lines.append(f"[{_timestamp()}] {line}")
                    _emit("app", f"[{_timestamp()}] {line}")
        except Exception:
            pass


_installed = False
_install_lock = threading.Lock()


def install():
    """Installs stdout/stderr tee + logging handler. Idempotent. Call once at startup."""
    global _installed
    with _install_lock:
        if _installed:
            return
        _installed = True
    try:
        sys.stdout = _TeeStream(sys.stdout, "stdout")  # type: ignore
        sys.stderr = _TeeStream(sys.stderr, "stderr")  # type: ignore
    except Exception:
        pass
    try:
        handler = _StoreHandler()
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        root = logging.getLogger()
        if not any(isinstance(h, _StoreHandler) for h in root.handlers):
            root.addHandler(handler)
        _logger.setLevel(logging.DEBUG)
    except Exception:
        pass
