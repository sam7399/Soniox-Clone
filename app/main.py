"""GlobalVoice AI - application entry point."""
from __future__ import annotations

import logging
import sys


def main() -> int:
    from app.logging_setup import setup_logging
    setup_logging()
    log = logging.getLogger("app.main")
    log.info("Starting GlobalVoice AI")

    from app.config import APP_NAME, get_config_manager
    from app.db.database import init_db
    from app.providers.registry import register_builtin_providers
    from app.core.jobs import get_queue

    init_db()                       # also recovers interrupted jobs
    register_builtin_providers()
    get_queue().start()

    from PySide6.QtWidgets import QApplication, QMessageBox
    from app.ui.theme import stylesheet
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    cfg = get_config_manager().config
    app.setStyleSheet(stylesheet(cfg.theme))

    # First-run notice (consent / privacy)
    if not cfg.first_run_done:
        QMessageBox.information(
            None, f"Welcome to {APP_NAME}",
            "Quick notes before you start:\n\n"
            "• Recording: always obtain consent from everyone being "
            "recorded. Recording laws vary by country and state; you "
            "are responsible for complying with them.\n\n"
            "• Cloud processing: if you configure a cloud provider, "
            "your audio/transcripts are sent to that provider. The "
            "current provider is always shown in the status bar. Use "
            "Privacy Mode (Settings) for fully local processing.\n\n"
            "• AI output: transcripts, translations and summaries are "
            "AI-generated and may contain errors - review before "
            "relying on them.")
        cfg.first_run_done = True
        get_config_manager().save()

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
