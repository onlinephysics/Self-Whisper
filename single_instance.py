"""
Self-Whisper single-instance guard.

Only one copy of the app may run: a second launch would fight the first over
the microphone, global hotkeys, and tray icon. Implemented with a
QLocalServer under a well-known name:

- First process to listen becomes the primary and keeps running.
- Any later process connects successfully, nudges the primary to the front,
  and exits immediately.

Stale servers left by a crash are removed before listening, so a previous
crash can never block a fresh start.
"""

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = "SelfWhisperSingleInstance_v1"


class SingleInstanceGuard(QObject):
    show_requested = pyqtSignal()  # secondary instance launched -> come forward

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None
        self.is_primary = False

    def try_acquire(self) -> bool:
        """Returns True for the primary (keep running), False to exit now."""
        # Nudge path: is somebody already serving?
        probe = QLocalSocket()
        try:
            probe.connectToServer(SERVER_NAME)
            if probe.waitForConnected(800):
                try:
                    probe.write(b"show")
                    probe.flush()
                    probe.waitForBytesWritten(800)
                except Exception:
                    pass
                try:
                    probe.disconnectFromServer()
                except Exception:
                    pass
                return False
        except Exception:
            pass
        finally:
            try:
                probe.close()
            except Exception:
                pass

        # Nobody home: clean a possibly stale socket and become primary.
        try:
            QLocalServer.removeServer(SERVER_NAME)
        except Exception:
            pass
        server = QLocalServer()
        try:
            server.newConnection.connect(self._on_new_connection)
        except Exception:
            pass
        try:
            if server.listen(SERVER_NAME):
                self._server = server
                self.is_primary = True
                return True
        except Exception:
            pass
        # Lost a race with another starter: exit and let it serve.
        try:
            server.close()
        except Exception:
            pass
        return False

    def _on_new_connection(self):
        try:
            sock = self._server.nextPendingConnection() if self._server else None
            if sock is not None:
                try:
                    sock.waitForReadyRead(300)
                    sock.close()
                except Exception:
                    pass
                try:
                    sock.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.show_requested.emit()
        except Exception:
            pass
