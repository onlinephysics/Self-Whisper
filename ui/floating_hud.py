"""
Self-Whisper Floating HUD Overlay
A sleek, modern Windows 11 Fluent dark-mode floating pill widget.
Features high-visibility glowing state borders (Red for Recording, Amber for AI, Green for Done),
an animated 7-bar dynamic equalizer visualizer, real-time transcript ticker,
and quick interactive controls.
"""

from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal, QRectF
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QFont, QLinearGradient, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGraphicsDropShadowEffect,
)


def _draw_mic_glyph(p, s: float, color="#FFFFFF"):
    """Vector microphone glyph painted into an active QPainter (no emoji)."""
    white = QBrush(QColor(color))
    cap_w, cap_h = s * 0.30, s * 0.46
    p.setBrush(white)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(
        QRectF((s - cap_w) / 2, s * 0.12, cap_w, cap_h), cap_w / 2, cap_w / 2)
    pen = QPen(QColor(color), max(2.0, s * 0.09))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(s * 0.20, s * 0.34, s * 0.60, s * 0.44), 0, -180 * 16)
    cx = s / 2
    p.drawLine(int(cx), int(s * 0.74), int(cx), int(s * 0.84))
    p.drawLine(int(s * 0.34), int(s * 0.84), int(s * 0.66), int(s * 0.84))


def make_hud_icon(kind: str, size: int = 20) -> QIcon:
    """Modern drawn icons for the record button (render everywhere, incl. Windows)."""
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    if kind == "mic":
        _draw_mic_glyph(p, s)
    elif kind == "stop":
        p.setBrush(QBrush(QColor("#FFFFFF")))
        p.setPen(Qt.PenStyle.NoPen)
        r = s * 0.26
        p.drawRoundedRect(QRectF(s / 2 - r, s / 2 - r, r * 2, r * 2), 4, 4)
    elif kind == "work":
        # three-dot "working" glyph
        p.setBrush(QBrush(QColor("#FFFFFF")))
        p.setPen(Qt.PenStyle.NoPen)
        for i, dx in enumerate((-1, 0, 1)):
            r = s * (0.10 if i != 1 else 0.13)
            p.drawEllipse(QRectF(s / 2 + dx * s * 0.24 - r, s / 2 - r, r * 2, r * 2))
    elif kind == "check":
        pen = QPen(QColor("#FFFFFF"), max(2.0, s * 0.12))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(int(s * 0.24), int(s * 0.54), int(s * 0.44), int(s * 0.72))
        p.drawLine(int(s * 0.44), int(s * 0.72), int(s * 0.78), int(s * 0.30))
    elif kind == "warn":
        p.setBrush(QBrush(QColor("#FFFFFF")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(s * 0.44, s * 0.22, s * 0.12, s * 0.38), 2, 2)
        p.drawEllipse(QRectF(s * 0.44, s * 0.66, s * 0.12, s * 0.12))
    elif kind == "gear":
        pen = QPen(QColor("#9aa3b8"), max(1.6, s * 0.09))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(s * 0.28, s * 0.28, s * 0.44, s * 0.44))
        for a in range(0, 360, 60):
            import math
            r1, r2 = s * 0.30, s * 0.40
            cx, cy = s / 2, s / 2
            t = math.radians(a)
            p.drawLine(int(cx + r1 * math.cos(t)), int(cy + r1 * math.sin(t)),
                       int(cx + r2 * math.cos(t)), int(cy + r2 * math.sin(t)))
    p.end()
    return QIcon(pix)


# Windows cannot render flag emoji (shows "BD" letters), so badges are
# plain text that renders in any font. Bengali script itself is fine.
LANGUAGE_BADGES = {
    "bn_primary": "BN · EN",
    "bn_only": "বাংলা",
    "en_only": "EN",
    "auto": "AUTO",
}


class ModernAudioVisualizer(QWidget):
    """Draws 5 animated gradient equalizer bars based on microphone RMS level."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 22)
        self.level = 0.0  # 0.0 to 1.0
        self.bar_heights = [0.15] * 5
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_animation)
        self.timer.start(25)  # 40 fps
        self.is_recording = False
        self.state = "idle"  # idle, listening, transcribing, done

    def set_level(self, level: float):
        self.level = max(0.0, min(1.0, level))

    def set_state(self, state: str):
        self.state = state
        self.is_recording = (state == "listening")
        if not self.is_recording:
            self.level = 0.0
        self.update()

    def _update_animation(self):
        import random
        if not self.is_recording:
            # Idle gentle breathing wave
            for i in range(5):
                self.bar_heights[i] = max(0.12, self.bar_heights[i] * 0.85)
        else:
            # Dynamic wave distribution mapped across 5 bars
            base = max(0.25, self.level)
            weights = [0.6, 1.1, 1.5, 1.1, 0.6]
            for i in range(5):
                target = min(1.0, base * weights[i] + random.uniform(-0.08, 0.12))
                self.bar_heights[i] = (self.bar_heights[i] * 0.3) + (target * 0.7)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bar_width = 3.5
        spacing = 3.0
        start_x = 2.0
        max_h = 18.0

        for i, h_ratio in enumerate(self.bar_heights):
            h = max(3.0, h_ratio * max_h)
            y = (self.height() - h) / 2.0
            x = start_x + i * (bar_width + spacing)

            rect = QRectF(x, y, bar_width, h)

            if self.state == "listening":
                # Vibrant gradient: SelfUI wrong/crimson tokens
                grad = QLinearGradient(x, y, x, y + h)
                grad.setColorAt(0.0, QColor("#f87171"))
                grad.setColorAt(1.0, QColor("#dc2626"))
                painter.setBrush(QBrush(grad))
            elif self.state == "transcribing":
                # SelfUI warning tokens
                grad = QLinearGradient(x, y, x, y + h)
                grad.setColorAt(0.0, QColor("#fbbf24"))
                grad.setColorAt(1.0, QColor("#d97706"))
                painter.setBrush(QBrush(grad))
            elif self.state == "done":
                # SelfUI accent/correct tokens
                grad = QLinearGradient(x, y, x, y + h)
                grad.setColorAt(0.0, QColor("#34d399"))
                grad.setColorAt(1.0, QColor("#0ea472"))
                painter.setBrush(QBrush(grad))
            else:
                # Idle slate (SelfUI border token)
                painter.setBrush(QBrush(QColor("#3a3f4c")))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 1.8, 1.8)


class FloatingHUD(QWidget):
    # Signals
    toggle_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    language_cycle_clicked = pyqtSignal()  # legacy: kept for compatibility
    language_picked = pyqtSignal(str)      # explicit menu choice, e.g. "bn_primary"

    def __init__(self, initial_x=None, initial_y=None):
        super().__init__()

        # Frameless, Always On Top, Non-activating Tool window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._drag_pos = QPoint()
        self._is_dragging = False
        self._drag_moved = False
        self._press_pos = QPoint()
        self._drag_threshold = 5  # px: below this it's a click, not a drag
        self.current_state = "idle"
        self._lang_mode = "bn_primary"

        self._init_ui()

        # Position HUD in bottom right corner (or saved coordinates)
        if initial_x is not None and initial_y is not None:
            self.move(initial_x, initial_y)
        else:
            self.position_bottom_right()

    def position_bottom_right(self):
        """Positions the HUD in the bottom-right corner of the primary screen."""
        try:
            screen = self.screen().availableGeometry()
            w = 216
            h = 58
            x = screen.right() - w - 24
            y = screen.bottom() - h - 24
            self.move(x, y)
        except Exception:
            pass

    def _init_ui(self):
        # Root layout with subtle shadow padding
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        # Main compact pill container
        self.container = QWidget(self)
        self.container.setObjectName("HudContainer")
        self.container.setFixedHeight(42)
        self.container.setFixedWidth(196)

        # Drop shadow glow effect
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(20)
        self.shadow.setColor(QColor(0, 0, 0, 160))
        self.shadow.setOffset(0, 3)
        self.container.setGraphicsEffect(self.shadow)

        layout = QHBoxLayout(self.container)
        layout.setContentsMargins(7, 3, 7, 3)
        layout.setSpacing(6)

        # 1. Recording / Action Button (modern drawn icon, no emoji)
        self.record_btn = QPushButton(self.container)
        self.record_btn.setObjectName("RecordBtn")
        self.record_btn.setFixedSize(30, 30)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setToolTip("Click to toggle dictation (or press Ctrl+Shift+Space)")
        self.record_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.record_btn.setIcon(make_hud_icon("mic"))
        self.record_btn.setIconSize(self.record_btn.size() * 0.72)
        self.record_btn.clicked.connect(self.toggle_clicked.emit)
        layout.addWidget(self.record_btn)

        # 2. Dynamic Audio Equalizer (5 bars)
        self.visualizer = ModernAudioVisualizer(self.container)
        layout.addWidget(self.visualizer)

        # 3. Language Badge Button (plain text — Windows has no flag emoji)
        self.lang_btn = QPushButton(LANGUAGE_BADGES["bn_primary"], self.container)
        self.lang_btn.setObjectName("LangBtn")
        self.lang_btn.setFixedHeight(24)
        self.lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_btn.setToolTip("Click to choose dictation language")
        self.lang_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lang_btn.clicked.connect(self._show_language_menu)
        layout.addWidget(self.lang_btn)

        # 4. Settings Gear Button (drawn gear icon)
        self.settings_btn = QPushButton(self.container)
        self.settings_btn.setObjectName("SettingsBtn")
        self.settings_btn.setFixedSize(26, 26)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.settings_btn.setIcon(make_hud_icon("gear"))
        self.settings_btn.setIconSize(self.settings_btn.size() * 0.66)
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        layout.addWidget(self.settings_btn)

        root_layout.addWidget(self.container)

        # Apply initial idle theme
        self._apply_theme("idle")

    def _apply_theme(self, state: str):
        """Applies dynamic theme and glowing borders based on state."""
        self.current_state = state

        if state == "listening":
            # SelfUI Vivid Crimson Glowing Border
            self.container.setStyleSheet("""
                QWidget#HudContainer {
                    background-color: rgba(28, 31, 38, 0.97);
                    border: 2px solid #f87171;
                    border-radius: 21px;
                }
                QPushButton#RecordBtn {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f87171, stop:1 #dc2626);
                    border: none;
                    border-radius: 15px;
                    color: #ffffff;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton#LangBtn {
                    background-color: rgba(220, 38, 38, 0.16);
                    border: 1px solid rgba(248, 113, 113, 0.5);
                    border-radius: 99px;
                    color: #fca5a5;
                    font-size: 10px;
                    font-weight: 600;
                    padding: 2px 7px;
                }
                QPushButton#SettingsBtn {
                    background-color: transparent;
                    border: none;
                    border-radius: 13px;
                    color: #9aa3b8;
                    font-size: 12px;
                }
                QPushButton#SettingsBtn:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                    color: #ffffff;
                }
            """)
            self.shadow.setColor(QColor(248, 113, 113, 160))
            self.shadow.setBlurRadius(24)

        elif state == "transcribing":
            # SelfUI Amber Gold Warning Glow
            self.container.setStyleSheet("""
                QWidget#HudContainer {
                    background-color: rgba(28, 31, 38, 0.97);
                    border: 2px solid #fbbf24;
                    border-radius: 21px;
                }
                QPushButton#RecordBtn {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fbbf24, stop:1 #d97706);
                    border: none;
                    border-radius: 15px;
                    color: #ffffff;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton#LangBtn {
                    background-color: rgba(217, 119, 6, 0.16);
                    border: 1px solid rgba(251, 191, 36, 0.5);
                    border-radius: 99px;
                    color: #fcd34d;
                    font-size: 10px;
                    font-weight: 600;
                    padding: 2px 7px;
                }
                QPushButton#SettingsBtn {
                    background-color: transparent;
                    border: none;
                    border-radius: 13px;
                    color: #9aa3b8;
                    font-size: 12px;
                }
                QPushButton#SettingsBtn:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                    color: #ffffff;
                }
            """)
            self.shadow.setColor(QColor(251, 191, 36, 150))
            self.shadow.setBlurRadius(22)

        elif state == "done":
            # SelfUI Emerald Green Accent Glow
            self.container.setStyleSheet("""
                QWidget#HudContainer {
                    background-color: rgba(28, 31, 38, 0.97);
                    border: 2px solid #34d399;
                    border-radius: 21px;
                }
                QPushButton#RecordBtn {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #34d399, stop:1 #0ea472);
                    border: none;
                    border-radius: 15px;
                    color: #ffffff;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton#LangBtn {
                    background-color: rgba(14, 164, 114, 0.16);
                    border: 1px solid rgba(52, 211, 153, 0.5);
                    border-radius: 99px;
                    color: #6ee7b7;
                    font-size: 10px;
                    font-weight: 600;
                    padding: 2px 7px;
                }
                QPushButton#SettingsBtn {
                    background-color: transparent;
                    border: none;
                    border-radius: 13px;
                    color: #9aa3b8;
                    font-size: 12px;
                }
                QPushButton#SettingsBtn:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                    color: #ffffff;
                }
            """)
            self.shadow.setColor(QColor(52, 211, 153, 160))
            self.shadow.setBlurRadius(22)

        else:
            # Idle Theme with SelfUI Dark Tokens (#1c1f26, #252930, #3a3f4c, #5b9cf6)
            self.container.setStyleSheet("""
                QWidget#HudContainer {
                    background-color: rgba(28, 31, 38, 0.96);
                    border: 1.5px solid #3a3f4c;
                    border-radius: 21px;
                }
                QPushButton#RecordBtn {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(91, 156, 246, 0.22), stop:1 rgba(37, 99, 235, 0.22));
                    border: 1px solid rgba(91, 156, 246, 0.35);
                    border-radius: 15px;
                    color: #5b9cf6;
                    font-size: 13px;
                }
                QPushButton#RecordBtn:hover {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
                    border-color: #5b9cf6;
                    color: #ffffff;
                }
                QPushButton#LangBtn {
                    background-color: #252930;
                    border: 1px solid #3a3f4c;
                    border-radius: 99px;
                    color: #5b9cf6;
                    font-size: 10px;
                    font-weight: 600;
                    padding: 2px 7px;
                }
                QPushButton#LangBtn:hover {
                    background-color: rgba(91, 156, 246, 0.14);
                    border-color: #5b9cf6;
                    color: #7db3f8;
                }
                QPushButton#SettingsBtn {
                    background-color: transparent;
                    border: none;
                    border-radius: 13px;
                    color: #9aa3b8;
                    font-size: 13px;
                }
                QPushButton#SettingsBtn:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                    color: #ffffff;
                }
            """)
            self.shadow.setColor(QColor(0, 0, 0, 140))
            self.shadow.setBlurRadius(16)

    def set_status(self, status: str, text: str = ""):
        """
        Updates HUD appearance and state:
        'idle', 'listening', 'transcribing', 'done', 'error'
        """
        self.visualizer.set_state(status)
        self._apply_theme(status)

        if status == "listening":
            self.record_btn.setIcon(make_hud_icon("stop"))
            self.setToolTip("Listening... Speak into microphone")

        elif status == "transcribing":
            self.record_btn.setIcon(make_hud_icon("work"))
            self.setToolTip("Finalizing transcription...")

        elif status == "done":
            self.record_btn.setIcon(make_hud_icon("check"))
            self.setToolTip("Dictation finalized!")
            QTimer.singleShot(1500, self._reset_to_idle)

        elif status == "error":
            self.record_btn.setIcon(make_hud_icon("warn"))
            self.setToolTip(text or "Error! Check Settings.")
            QTimer.singleShot(3000, self._reset_to_idle)

        else:
            self._reset_to_idle()

    def _reset_to_idle(self):
        self._apply_theme("idle")
        self.visualizer.set_state("idle")
        self.record_btn.setIcon(make_hud_icon("mic"))
        self.setToolTip("Self-Whisper (Ctrl+Shift+Space to talk)")

    def update_audio_level(self, level: float):
        self.visualizer.set_level(level)

    def set_preview_text(self, text: str):
        """Kept for API compatibility; text is written live to active window."""
        pass

    def update_language_badge(self, lang_mode: str):
        self._lang_mode = lang_mode
        self.lang_btn.setText(LANGUAGE_BADGES.get(lang_mode, LANGUAGE_BADGES["bn_primary"]))

    def _show_language_menu(self):
        """Explicit picker (with checkmark) instead of blind per-click cycling,
        so the mode can never change by an accidental badge click."""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QCursor
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #252930;
                color: #e8ecf4;
                border: 1px solid #3a3f4c;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 22px;
                border-radius: 4px;
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
        """)
        options = [
            ("bn_primary", "Bangla + English"),
            ("bn_only", "Bangla only"),
            ("en_only", "English only"),
            ("auto", "Auto detect"),
        ]
        current = getattr(self, "_lang_mode", "bn_primary")
        for mode, label in options:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(mode == current)
            act.triggered.connect(lambda _c=False, m=mode: self.language_picked.emit(m))
        menu.exec(QCursor.pos())

    # Draggable HUD Window Implementation
    # NOTE: drag only starts on the pill background, never on buttons.
    # Presses starting on a QPushButton are left alone so single-click toggle
    # always reaches the button (previously any press could be swallowed as drag).
    def _press_started_on_button(self, pos) -> bool:
        try:
            from PyQt6.QtWidgets import QPushButton as _PB
            child = self.childAt(pos)
            while child is not None:
                if isinstance(child, _PB):
                    return True
                child = child.parentWidget() if hasattr(child, "parentWidget") else None
        except Exception:
            pass
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._press_started_on_button(event.pos()):
                event.ignore()
                return
            self._is_dragging = True
            self._drag_moved = False
            self._press_pos = event.globalPosition().toPoint()
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._is_dragging and event.buttons() == Qt.MouseButton.LeftButton:
            if not self._drag_moved:
                try:
                    dist = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
                except Exception:
                    dist = self._drag_threshold + 1
                if dist < self._drag_threshold:
                    event.ignore()
                    return
                self._drag_moved = True
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        self._is_dragging = False
        self._drag_moved = False
        event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        try:
            import ctypes
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            hwnd = int(self.winId())
            cur = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, cur | WS_EX_NOACTIVATE)
        except Exception:
            pass

