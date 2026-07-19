"""Main window: sidebar navigation + stacked pages + status bar."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QStatusBar,
                               QVBoxLayout, QWidget)

from app.config import APP_NAME, APP_VERSION, get_config_manager
from app.core.jobs import get_queue
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.editor import EditorPage
from app.ui.pages.live import LivePage
from app.ui.pages.sessions import SessionsPage
from app.ui.pages.settings import SettingsPage
from app.ui.pages.tts import TTSPage
from app.ui.pages.upload import UploadPage
from app.ui.pages.vocabulary import VocabularyPage

NAV = [
    ("dashboard", "  Dashboard"),
    ("live", "  Live Transcription"),
    ("upload", "  Upload & Queue"),
    ("sessions", "  Sessions"),
    ("tts", "  Text-to-Speech"),
    ("vocab", "  Vocabulary"),
    ("settings", "  Settings"),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        cfg = get_config_manager().config
        self.setWindowTitle(f"{cfg.app_name or APP_NAME} — v{APP_VERSION}")
        self.resize(1280, 800)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        # Sidebar ------------------------------------------------------
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 12)
        title = QLabel(cfg.app_name or APP_NAME)
        title.setObjectName("AppTitle")
        sl.addWidget(title)
        self._nav_buttons: dict[str, QPushButton] = {}
        for key, label in NAV:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.navigate(k))
            sl.addWidget(btn)
            self._nav_buttons[key] = btn
        sl.addStretch(1)
        self._privacy_label = QLabel("")
        self._privacy_label.setProperty("muted", True)
        self._privacy_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addWidget(self._privacy_label)
        layout.addWidget(sidebar)

        # Pages --------------------------------------------------------
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(self),
            "live": LivePage(self),
            "upload": UploadPage(self),
            "sessions": SessionsPage(self),
            "editor": EditorPage(self),
            "tts": TTSPage(self),
            "vocab": VocabularyPage(self),
            "settings": SettingsPage(self),
        }
        for p in self.pages.values():
            self.stack.addWidget(p)

        # Status bar ---------------------------------------------------
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_jobs = QLabel("")
        self._status_mode = QLabel("")
        sb.addPermanentWidget(self._status_jobs)
        sb.addPermanentWidget(self._status_mode)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh_status)
        self._tick.start(2000)

        self.navigate("dashboard")
        self._refresh_status()

    # -- navigation ---------------------------------------------------
    def navigate(self, key: str, **kwargs) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        for k, btn in self._nav_buttons.items():
            btn.setProperty("active", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if hasattr(page, "on_show"):
            page.on_show(**kwargs)

    def open_session(self, session_id: int) -> None:
        self.navigate("editor", session_id=session_id)

    # -- status -------------------------------------------------------
    def _refresh_status(self) -> None:
        cfg = get_config_manager().config
        pending = get_queue().pending_count()
        self._status_jobs.setText(
            f"Jobs in queue: {pending}   " if pending else "")
        mode = "Privacy Mode: local only" if cfg.privacy_mode else \
            f"Provider: {cfg.stt_provider}"
        self._status_mode.setText(mode + "  ")
        self._privacy_label.setText(
            "🔒 Privacy Mode" if cfg.privacy_mode else "")

    def closeEvent(self, event) -> None:  # noqa: N802
        live = self.pages.get("live")
        if live is not None and getattr(live, "recorder", None) and \
                live.recorder.is_recording:
            live.stop_recording()
        get_queue().shutdown(timeout=2)
        super().closeEvent(event)
