"""
Self-Whisper Settings Dialog
Styled with SelfUI Design System (selfstudy.xyz)
Tabbed layout (no scrolling): Connection / Language / Microphone / Shortcuts / Logs.
"""

import json
import urllib.request
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QPixmap, QPainter, QColor, QBrush, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QFrame,
    QMessageBox,
    QCheckBox,
    QProgressBar,
    QTabWidget,
    QPlainTextEdit,
    QListWidget,
    QApplication,
)

from config import config
from audio_capture import list_input_devices, AudioCaptureEngine


def create_mic_pixmap(size: int = 22, bg: str = "#2563eb") -> QPixmap:
    """Modern vector microphone glyph (no emoji dependency)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    # backdrop disc
    p.setBrush(QBrush(QColor(bg)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)
    # mic capsule
    white = QBrush(QColor("#FFFFFF"))
    cap_w, cap_h = s * 0.26, s * 0.44
    p.setBrush(white)
    p.drawRoundedRect(
        int((s - cap_w) / 2), int(s * 0.16), int(cap_w), int(cap_h),
        int(cap_w / 2), int(cap_w / 2),
    )
    # arch
    pen = QPen(QColor("#FFFFFF"), max(2, int(s * 0.07)))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(int(s * 0.24), int(s * 0.34), int(s * 0.52), int(s * 0.40), 0, -180 * 16)
    # stem + base
    cx = int(s / 2)
    p.drawLine(cx, int(s * 0.72), cx, int(s * 0.80))
    p.drawLine(int(s * 0.36), int(s * 0.80), int(s * 0.64), int(s * 0.80))
    p.end()
    return pixmap


class SettingsDialog(QDialog):
    settings_saved = pyqtSignal()
    hud_reset_requested = pyqtSignal()
    mic_level = pyqtSignal(int)  # thread-safe volume meter (audio thread -> GUI)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Self-Whisper Settings")
        self.resize(660, 560)
        self.setMinimumSize(620, 500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._test_audio_engine = None
        self.mic_level.connect(self._set_meter)
        self._init_styling()
        self._init_ui()
        self._load_values()
        self._load_logs()

    def _init_styling(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1c1f26;
                color: #e8ecf4;
                font-family: 'Segoe UI Variable Text', 'Segoe UI', Arial, sans-serif;
            }
            QTabWidget::pane {
                background-color: #1c1f26;
                border: 1px solid #3a3f4c;
                border-radius: 10px;
                padding: 6px;
            }
            QTabBar::tab {
                background-color: #252930;
                color: #9aa3b8;
                border: 1px solid #3a3f4c;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 7px 14px;
                margin-right: 4px;
                font-size: 12px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background-color: #2563eb;
                color: #ffffff;
                border-color: #3b82f6;
            }
            QTabBar::tab:hover:!selected {
                background-color: #2f333d;
                color: #e8ecf4;
            }
            QFrame.selfui-card {
                background-color: #252930;
                border: 1px solid #3a3f4c;
                border-radius: 12px;
            }
            QLabel {
                color: #e8ecf4;
                font-size: 12px;
            }
            QLabel.hint {
                color: #9aa3b8;
                font-size: 11px;
            }
            QLineEdit {
                background-color: #1c1f26;
                border: 1.5px solid #3a3f4c;
                border-radius: 8px;
                color: #e8ecf4;
                padding: 7px 11px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #5b9cf6;
            }
            QComboBox {
                background-color: #1c1f26;
                border: 1.5px solid #3a3f4c;
                border-radius: 8px;
                color: #e8ecf4;
                padding: 6px 10px;
                font-size: 12px;
            }
            QComboBox:focus {
                border-color: #5b9cf6;
            }
            QComboBox QAbstractItemView {
                background-color: #252930;
                color: #e8ecf4;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
                border: 1.5px solid #3a3f4c;
                padding: 4px;
                outline: none;
            }
            QRadioButton, QCheckBox {
                color: #e8ecf4;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1.5px solid #3a3f4c;
                border-radius: 4px;
                background: #1c1f26;
            }
            QCheckBox::indicator:checked {
                background-color: #2563eb;
                border-color: #5b9cf6;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border: 1.5px solid #3a3f4c;
                border-radius: 8px;
                background: #1c1f26;
            }
            QRadioButton::indicator:checked {
                background-color: #2563eb;
                border-color: #5b9cf6;
            }
            QPushButton {
                background-color: #2f333d;
                border: 1px solid #3a3f4c;
                border-radius: 8px;
                color: #e8ecf4;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3a3f4c;
                color: #ffffff;
            }
            QPushButton#PrimaryBtn {
                background-color: #2563eb;
                border: 1px solid #3b82f6;
                color: #ffffff;
                font-weight: 600;
                padding: 8px 20px;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #1d4ed8;
            }
            QPushButton#ActionBtn {
                background-color: rgba(91, 156, 246, 0.12);
                border: 1px solid #5b9cf6;
                color: #5b9cf6;
                padding: 6px 12px;
                font-weight: 600;
            }
            QPushButton#ActionBtn:hover {
                background-color: rgba(91, 156, 246, 0.25);
                color: #7db3f8;
            }
            QProgressBar {
                background-color: #1c1f26;
                border: 1px solid #3a3f4c;
                border-radius: 6px;
                height: 12px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea472, stop:1 #34d399);
                border-radius: 5px;
            }
            QPlainTextEdit, QListWidget {
                background-color: #14161b;
                border: 1px solid #3a3f4c;
                border-radius: 8px;
                color: #d6dbe6;
                font-family: Consolas, monospace;
                font-size: 11px;
                padding: 6px;
            }
        """)

    def _create_card(self, title: str, parent: QWidget) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(parent)
        card.setProperty("class", "selfui-card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 14)
        card_layout.setSpacing(8)
        header = QLabel(title, card)
        header.setStyleSheet("color: #5b9cf6; font-size: 13px; font-weight: 700;")
        card_layout.addWidget(header)
        return card, card_layout

    def _open_selfstudy_site(self):
        QDesktopServices.openUrl(QUrl("https://www.selfstudy.xyz"))

    # ------------------------------------------------------------------ UI --
    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header_widget = QWidget(self)
        header_widget.setStyleSheet("background-color: #252930; border-bottom: 1px solid #3a3f4c;")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(18, 12, 18, 12)

        brand_icon = QLabel(header_widget)
        brand_icon.setPixmap(create_mic_pixmap(30))
        header_layout.addWidget(brand_icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_label = QLabel("Self-Whisper Settings", header_widget)
        title_label.setStyleSheet("font-size: 16px; font-weight: 800; color: #e8ecf4;")
        title_box.addWidget(title_label)
        sub_label = QLabel("Gemini Live speech-to-text for Windows", header_widget)
        sub_label.setProperty("class", "hint")
        title_box.addWidget(sub_label)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)

        self.site_btn = QPushButton("selfstudy.xyz", header_widget)
        self.site_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.site_btn.setToolTip("Visit Self Study (https://www.selfstudy.xyz)")
        self.site_btn.clicked.connect(self._open_selfstudy_site)
        header_layout.addWidget(self.site_btn)
        main_layout.addWidget(header_widget)

        # Tabs (fixed height content -> no scrolling needed)
        self.tabs = QTabWidget(self)
        tab_wrap = QWidget(self)
        tab_wrap_layout = QVBoxLayout(tab_wrap)
        tab_wrap_layout.setContentsMargins(14, 10, 14, 10)
        tab_wrap_layout.addWidget(self.tabs)
        main_layout.addWidget(tab_wrap, 1)

        self._build_connection_tab()
        self._build_language_tab()
        self._build_mic_tab()
        self._build_shortcuts_tab()
        self._build_logs_tab()

        # Footer
        footer_widget = QWidget(self)
        footer_widget.setStyleSheet("background-color: #252930; border-top: 1px solid #3a3f4c;")
        footer_layout = QHBoxLayout(footer_widget)
        footer_layout.setContentsMargins(18, 10, 18, 10)
        footer_layout.addStretch(1)
        self.cancel_btn = QPushButton("Cancel", footer_widget)
        self.cancel_btn.clicked.connect(self._on_cancel)
        footer_layout.addWidget(self.cancel_btn)
        self.save_btn = QPushButton("Save Settings", footer_widget)
        self.save_btn.setObjectName("PrimaryBtn")
        self.save_btn.clicked.connect(self._save_values)
        footer_layout.addWidget(self.save_btn)
        main_layout.addWidget(footer_widget)

    def _build_connection_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        card, cl = self._create_card("Google AI Studio API", tab)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self.api_key_input = QLineEdit(tab)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Paste Google AI Studio API Key (AIzaSy...)")
        key_row.addWidget(self.api_key_input, 1)
        self.show_key_btn = QPushButton("Show", tab)
        self.show_key_btn.setFixedWidth(60)
        self.show_key_btn.setToolTip("Show / Hide API Key")
        self.show_key_btn.clicked.connect(self._toggle_key_visibility)
        key_row.addWidget(self.show_key_btn)
        cl.addLayout(key_row)

        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        model_row.addWidget(QLabel("Model:", tab))
        self.model_combo = QComboBox(tab)
        self.model_combo.setEditable(True)
        self.model_combo.addItems([
            "gemini-3.5-transcribe-live",
            "gemini-2.0-flash",
            "gemini-2.0-flash-exp",
        ])
        model_row.addWidget(self.model_combo, 1)
        self.test_btn = QPushButton("Test Connection", tab)
        self.test_btn.setObjectName("ActionBtn")
        self.test_btn.clicked.connect(self._test_api_key)
        model_row.addWidget(self.test_btn)
        cl.addLayout(model_row)
        layout.addWidget(card)

        hint = QLabel("Get a free key from Google AI Studio, paste it above, then Test Connection.", tab)
        hint.setProperty("class", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.tabs.addTab(tab, "Connection")

    def _build_language_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        card, cl = self._create_card("Language & Transcription", tab)
        form = QFormLayout()
        form.setSpacing(10)

        self.lang_combo = QComboBox(tab)
        # NOTE: no flag emoji — Windows cannot render flag glyphs (shows "BD" text).
        self.lang_combo.addItem("Bangla + English (bilingual)", "bn_primary")
        self.lang_combo.addItem("Bangla only", "bn_only")
        self.lang_combo.addItem("English only", "en_only")
        self.lang_combo.addItem("Auto detect", "auto")
        form.addRow("Language focus:", self.lang_combo)

        self.correct_combo = QComboBox(tab)
        self.correct_combo.addItem("High: fix grammar, stutters, punctuate", "high")
        self.correct_combo.addItem("Normal: punctuation only", "normal")
        self.correct_combo.addItem("Verbatim: exact words", "verbatim")
        form.addRow("Auto-correction:", self.correct_combo)

        self.sound_check = QCheckBox("Play chime on recording start/stop", tab)
        form.addRow("Sound:", self.sound_check)
        cl.addLayout(form)
        layout.addWidget(card)

        card2, cl2 = self._create_card("Dictation Engine", tab)
        self.typewriter_radio = QRadioButton("Live typing (writes into the app as you speak)", tab)
        self.smart_paste_radio = QRadioButton("Block paste (paste once when you stop)", tab)
        self.inject_btn_group = QButtonGroup(tab)
        self.inject_btn_group.addButton(self.typewriter_radio, 1)
        self.inject_btn_group.addButton(self.smart_paste_radio, 2)
        cl2.addWidget(self.typewriter_radio)
        cl2.addWidget(self.smart_paste_radio)
        layout.addWidget(card2)

        card3, cl3 = self._create_card("Floating Bar", tab)
        self.auto_hide_check = QCheckBox("Auto-hide bar (show only while recording)", tab)
        cl3.addWidget(self.auto_hide_check)
        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("Bar lives in the bottom-right corner.", tab), 1)
        self.reset_hud_btn = QPushButton("Reset Position", tab)
        self.reset_hud_btn.clicked.connect(self._reset_hud_position)
        pos_row.addWidget(self.reset_hud_btn)
        cl3.addLayout(pos_row)
        layout.addWidget(card3)
        layout.addStretch(1)
        self.tabs.addTab(tab, "Language & Voice")

    def _build_mic_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        card, cl = self._create_card("Microphone & Audio Input", tab)

        dev_row = QHBoxLayout()
        dev_row.setSpacing(8)
        dev_row.addWidget(QLabel("Device:", tab))
        self.device_combo = QComboBox(tab)
        self.device_combo.addItem("Default System Microphone", -1)
        for idx, name in list_input_devices():
            self.device_combo.addItem(f"[{idx}] {name}", idx)
        dev_row.addWidget(self.device_combo, 1)
        self.test_mic_btn = QPushButton("Test Mic", tab)
        self.test_mic_btn.setObjectName("ActionBtn")
        self.test_mic_btn.setMinimumWidth(100)
        self.test_mic_btn.clicked.connect(self._toggle_mic_test)
        dev_row.addWidget(self.test_mic_btn)
        cl.addLayout(dev_row)

        meter_row = QHBoxLayout()
        meter_row.setSpacing(8)
        meter_row.addWidget(QLabel("Volume:", tab))
        self.volume_bar = QProgressBar(tab)
        self.volume_bar.setRange(0, 100)
        self.volume_bar.setValue(0)
        self.volume_bar.setTextVisible(False)
        meter_row.addWidget(self.volume_bar, 1)
        self.volume_label = QLabel("0%", tab)
        self.volume_label.setFixedWidth(38)
        meter_row.addWidget(self.volume_label)
        cl.addLayout(meter_row)
        layout.addWidget(card)

        hint = QLabel("Press Test Mic and speak — the bar should move with your voice. Press Stop Test when done.", tab)
        hint.setProperty("class", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.tabs.addTab(tab, "Microphone")

    def _build_shortcuts_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        card, cl = self._create_card("Global Shortcuts (both always active)", tab)
        form = QFormLayout()
        form.setSpacing(10)

        self.toggle_key_input = QLineEdit(tab)
        self.toggle_key_input.setPlaceholderText("ctrl+shift+space")
        form.addRow("Toggle (press to start/stop):", self.toggle_key_input)

        self.ptt_key_input = QLineEdit(tab)
        self.ptt_key_input.setPlaceholderText("f8")
        form.addRow("Push-to-talk (hold to talk):", self.ptt_key_input)
        cl.addLayout(form)

        info = QLabel(
            "Both shortcuts work at the same time — no mode to pick. "
            "Releasing push-to-talk only stops a session it started, "
            "so it can never cut off a toggle dictation.", tab)
        info.setProperty("class", "hint")
        info.setWordWrap(True)
        cl.addWidget(info)
        layout.addWidget(card)
        layout.addStretch(1)
        self.tabs.addTab(tab, "Shortcuts")

    def _build_logs_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        hist_row = QHBoxLayout()
        hist_row.addWidget(QLabel("Dictation history:", tab), 1)
        self.copy_hist_btn = QPushButton("Copy", tab)
        self.copy_hist_btn.clicked.connect(self._copy_history)
        hist_row.addWidget(self.copy_hist_btn)
        layout.addLayout(hist_row)

        self.history_list = QListWidget(tab)
        self.history_list.setMinimumHeight(120)
        layout.addWidget(self.history_list, 1)

        log_row = QHBoxLayout()
        log_row.addWidget(QLabel("Application log:", tab), 1)
        self.copy_log_btn = QPushButton("Copy All", tab)
        self.copy_log_btn.clicked.connect(self._copy_all)
        log_row.addWidget(self.copy_log_btn)
        self.clear_log_btn = QPushButton("Clear", tab)
        self.clear_log_btn.clicked.connect(self._clear_logs)
        log_row.addWidget(self.clear_log_btn)
        layout.addLayout(log_row)

        self.log_view = QPlainTextEdit(tab)
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(140)
        layout.addWidget(self.log_view, 2)

        self.tabs.addTab(tab, "Logs")

    # ---------------------------------------------------------------- logs --
    def _load_logs(self):
        try:
            from log_store import get_app_lines, get_dictations, log_hub
            for ts, text in get_dictations():
                self.history_list.addItem(f"[{ts}] {text}")
            self.history_list.scrollToBottom()
            self.log_view.setPlainText("\n".join(get_app_lines()))
            self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum())
            if log_hub is not None:
                try:
                    log_hub.new_entry.disconnect(self._on_log_entry)
                except Exception:
                    pass
                log_hub.new_entry.connect(self._on_log_entry)
        except Exception:
            pass

    def _on_log_entry(self, kind: str, line: str):
        try:
            if kind == "clear":
                self.history_list.clear()
                self.log_view.clear()
                return
            if kind == "dictation":
                self.history_list.addItem(line)
                self.history_list.scrollToBottom()
            elif line:
                self.log_view.appendPlainText(line)
        except Exception:
            pass

    def _copy_history(self):
        try:
            from log_store import get_dictations
            text = "\n".join(f"[{ts}] {t}" for ts, t in get_dictations())
            QApplication.clipboard().setText(text)
        except Exception:
            pass

    def _copy_all(self):
        try:
            from log_store import get_logs_text
            QApplication.clipboard().setText(get_logs_text())
        except Exception:
            pass

    def _clear_logs(self):
        try:
            from log_store import clear_all
            clear_all()
        except Exception:
            self.history_list.clear()
            self.log_view.clear()

    # --------------------------------------------------------------- mic ----
    def _reset_hud_position(self):
        config.set("hud_x", None, auto_save=False)
        config.set("hud_y", None, auto_save=True)
        self.hud_reset_requested.emit()
        QMessageBox.information(self, "Bar Position Reset", "The floating bar was reset to the bottom-right corner.")

    def _toggle_mic_test(self):
        """Starts or stops the real-time microphone test meter."""
        if self._test_audio_engine and self._test_audio_engine.is_recording:
            self._stop_mic_test()
            self.test_mic_btn.setText("Test Mic")
            self._set_meter(0)
        else:
            dev_idx = self.device_combo.currentData()
            if dev_idx == -1:
                dev_idx = None
            self._test_audio_engine = AudioCaptureEngine(
                device_index=dev_idx,
                # Runs on the audio thread -> must only emit the signal.
                level_callback=lambda lv: self.mic_level.emit(int(lv * 100)),
            )
            started = self._test_audio_engine.start()
            if started:
                self.test_mic_btn.setText("Stop Test")
            else:
                self._test_audio_engine = None
                QMessageBox.warning(self, "Mic Error", "Could not open the selected microphone. Try another device.")

    def _set_meter(self, percent: int):
        """GUI-thread slot: actually moves the volume bar."""
        try:
            percent = max(0, min(100, int(percent)))
        except Exception:
            percent = 0
        try:
            if self.volume_bar is not None:
                self.volume_bar.setValue(percent)
            if self.volume_label is not None:
                self.volume_label.setText(f"{percent}%")
        except Exception:
            pass

    def _stop_mic_test(self):
        if self._test_audio_engine:
            try:
                self._test_audio_engine.stop()
            except Exception:
                pass
            self._test_audio_engine = None

    def _on_cancel(self):
        self._stop_mic_test()
        self.reject()

    def closeEvent(self, event):
        self._stop_mic_test()
        super().closeEvent(event)

    def _toggle_key_visibility(self):
        if self.api_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_key_btn.setText("Hide")
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_key_btn.setText("Show")

    def _test_api_key(self):
        key = self.api_key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "API Key Required", "Please enter a Google AI Studio API key first.")
            return
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("models", [])
                QMessageBox.information(
                    self, "Connection Successful",
                    f"Connected to Google AI Studio! {len(models)} accessible models.",
                )
        except Exception as e:
            QMessageBox.critical(self, "Connection Failed", f"Could not connect with this key:\n{e}")

    def _load_values(self):
        self.api_key_input.setText(config.get("api_key", ""))
        self.model_combo.setCurrentText(config.get("model", "gemini-3.5-transcribe-live"))

        lang_idx = self.lang_combo.findData(config.get("language_mode", "bn_primary"))
        if lang_idx != -1:
            self.lang_combo.setCurrentIndex(lang_idx)

        cor_idx = self.correct_combo.findData(config.get("correction_level", "high"))
        if cor_idx != -1:
            self.correct_combo.setCurrentIndex(cor_idx)

        self.sound_check.setChecked(config.get("sound_effects_enabled", True))
        self.auto_hide_check.setChecked(config.get("auto_hide_hud", False))

        inj = config.get("injection_mode", "typewriter")
        if inj == "smart_paste":
            self.smart_paste_radio.setChecked(True)
        else:
            self.typewriter_radio.setChecked(True)

        self.toggle_key_input.setText(config.get("hotkey_toggle", "<ctrl>+<shift>+<space>"))
        self.ptt_key_input.setText(config.get("hotkey_push_to_talk", "<f8>"))

        dev_idx = config.get("input_device_index")
        if dev_idx is None or dev_idx == -1:
            self.device_combo.setCurrentIndex(0)
        else:
            for i in range(self.device_combo.count()):
                if self.device_combo.itemData(i) == dev_idx:
                    self.device_combo.setCurrentIndex(i)
                    break

    def _save_values(self):
        self._stop_mic_test()

        chosen_device = self.device_combo.currentData()
        if chosen_device == -1:
            chosen_device = None

        inj_mode = "smart_paste" if self.smart_paste_radio.isChecked() else "typewriter"

        updates = {
            "api_key": self.api_key_input.text().strip(),
            "model": self.model_combo.currentText().strip(),
            "language_mode": self.lang_combo.currentData(),
            "correction_level": self.correct_combo.currentData(),
            "sound_effects_enabled": self.sound_check.isChecked(),
            "auto_hide_hud": self.auto_hide_check.isChecked(),
            "injection_mode": inj_mode,
            "hotkey_toggle": self.toggle_key_input.text().strip(),
            "hotkey_push_to_talk": self.ptt_key_input.text().strip(),
            "input_device_index": chosen_device,
        }

        config.update(updates, auto_save=True)
        self.settings_saved.emit()
        self.accept()
