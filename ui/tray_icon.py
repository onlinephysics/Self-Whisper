"""
Self-Whisper System Tray Icon
Provides unobtrusive background execution, quick context menu,
and tray notifications for Windows.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QPen
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu


def create_tray_pixmap(is_active: bool = False) -> QPixmap:
    """Generates a high-DPI custom tray icon dynamically."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Background circle
    bg_color = QColor("#EF4444") if is_active else QColor("#0284C7")
    painter.setBrush(QBrush(bg_color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)

    # Inner mic silhouette
    painter.setBrush(QBrush(QColor("#FFFFFF")))
    # Mic capsule
    painter.drawRoundedRect(25, 16, 14, 24, 7, 7)
    # Mic stand arch
    pen = QPen(QColor("#FFFFFF"), 3)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(20, 24, 24, 20, 0, -180 * 16)
    # Mic stem & base
    painter.drawLine(32, 44, 32, 50)
    painter.drawLine(24, 50, 40, 50)

    painter.end()
    return pixmap


from PyQt6.QtCore import Qt


class SelfWhisperTray(QSystemTrayIcon):
    toggle_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    toggle_hud_requested = pyqtSignal()
    exit_requested = pyqtSignal()
    language_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.normal_icon = QIcon(create_tray_pixmap(is_active=False))
        self.active_icon = QIcon(create_tray_pixmap(is_active=True))

        self.setIcon(self.normal_icon)
        self.setToolTip("Self-Whisper: Gemini Live Speech-to-Text")

        self._create_menu()
        self.activated.connect(self._on_activated)

    def _create_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #1E2235;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0284C7;
                color: #FFFFFF;
            }
        """)

        self.toggle_action = menu.addAction("Toggle Dictation")
        self.toggle_action.triggered.connect(self.toggle_requested.emit)

        self.hud_action = menu.addAction("Toggle Floating Bar")
        self.hud_action.triggered.connect(self.toggle_hud_requested.emit)

        menu.addSeparator()

        # Language submenu (no flag emoji: Windows cannot render flag glyphs)
        lang_menu = menu.addMenu("Language Focus")
        self.action_bn_primary = lang_menu.addAction("Bangla + English (bilingual)")
        self.action_bn_only = lang_menu.addAction("Bangla only")
        self.action_en_only = lang_menu.addAction("English only")
        self.action_auto = lang_menu.addAction("Auto detect")

        self.action_bn_primary.triggered.connect(lambda: self.language_changed.emit("bn_primary"))
        self.action_bn_only.triggered.connect(lambda: self.language_changed.emit("bn_only"))
        self.action_en_only.triggered.connect(lambda: self.language_changed.emit("en_only"))
        self.action_auto.triggered.connect(lambda: self.language_changed.emit("auto"))

        menu.addSeparator()

        settings_action = menu.addAction("Settings...")
        settings_action.triggered.connect(self.settings_requested.emit)

        exit_action = menu.addAction("Exit Self-Whisper")
        exit_action.triggered.connect(self.exit_requested.emit)

        self.setContextMenu(menu)

    def set_recording_state(self, is_recording: bool):
        if is_recording:
            self.setIcon(self.active_icon)
            self.setToolTip("Self-Whisper: Recording & Streaming Audio...")
        else:
            self.setIcon(self.normal_icon)
            self.setToolTip("Self-Whisper: Ready (Press Ctrl+Shift+Space)")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_requested.emit()
