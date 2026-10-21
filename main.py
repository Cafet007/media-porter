"""
Media Porter — entry point.
Run: python3 main.py
"""

import sys
from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow
from backend.utils.log_setup import setup as setup_logging, get_log_path


def main():
    setup_logging(level="INFO")

    import logging
    logging.getLogger(__name__).info("Media Porter starting up")

    app = QApplication(sys.argv)
    app.setApplicationName("Media Porter")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
