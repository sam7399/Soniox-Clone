"""Application-wide Qt stylesheets (dark and light)."""

ACCENT = "#4F8EF7"

DARK = f"""
* {{ font-family: 'Segoe UI', sans-serif; font-size: 13px; }}
QMainWindow, QWidget {{ background: #1e2228; color: #e8eaed; }}
#Sidebar {{ background: #171a1f; border: none; }}
#Sidebar QPushButton {{
    text-align: left; padding: 10px 18px; border: none; color: #aab0b8;
    background: transparent; border-radius: 6px; margin: 2px 8px;
}}
#Sidebar QPushButton:hover {{ background: #232830; color: #fff; }}
#Sidebar QPushButton[active="true"] {{
    background: {ACCENT}22; color: {ACCENT}; font-weight: 600;
}}
#AppTitle {{ font-size: 16px; font-weight: 700; color: #ffffff;
             padding: 16px; }}
QPushButton {{
    background: #2a303a; border: 1px solid #3a4150; border-radius: 6px;
    padding: 7px 14px; color: #e8eaed;
}}
QPushButton:hover {{ background: #333a46; }}
QPushButton:disabled {{ color: #667; }}
QPushButton[primary="true"] {{
    background: {ACCENT}; border-color: {ACCENT}; color: white;
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: #3d7ce8; }}
QPushButton[danger="true"] {{ background: #a33; border-color: #a33;
                              color: white; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit,
QPlainTextEdit {{
    background: #171a1f; border: 1px solid #3a4150; border-radius: 6px;
    padding: 6px 8px; color: #e8eaed; selection-background-color: {ACCENT};
}}
QTableWidget, QTableView, QListWidget {{
    background: #171a1f; border: 1px solid #2a303a; border-radius: 6px;
    gridline-color: #2a303a; alternate-background-color: #1b1f26;
}}
QHeaderView::section {{
    background: #232830; color: #aab0b8; border: none; padding: 6px;
    font-weight: 600;
}}
QProgressBar {{ background: #171a1f; border: 1px solid #3a4150;
    border-radius: 6px; text-align: center; color: #e8eaed; height: 16px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QTabWidget::pane {{ border: 1px solid #2a303a; border-radius: 6px; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px;
    color: #aab0b8; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid
    {ACCENT}; }}
QLabel[h1="true"] {{ font-size: 20px; font-weight: 700; }}
QLabel[h2="true"] {{ font-size: 15px; font-weight: 600; color: #cfd3d8; }}
QLabel[muted="true"] {{ color: #8a919b; }}
QLabel[recording="true"] {{ color: #ff5555; font-weight: 700; }}
QStatusBar {{ background: #171a1f; color: #8a919b; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #3a4150; border-radius: 5px;
    min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QGroupBox {{ border: 1px solid #2a303a; border-radius: 8px;
    margin-top: 12px; padding-top: 18px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px;
    padding: 0 4px; color: #cfd3d8; }}
"""

LIGHT = DARK  # v1 ships dark theme; light palette planned for v1.1


def stylesheet(theme: str) -> str:
    return DARK if theme != "light" else LIGHT
