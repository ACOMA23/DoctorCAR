import argparse
import logging
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="DoctorCAR M1 — local simulation only")
    parser.add_argument("--database", type=Path, default=Path("data/doctorcar.sqlite3"))
    parser.add_argument("--no-splash", action="store_true", help="skip the startup splash window")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    app.setApplicationName("DoctorCAR")
    from doctorcar.ui.startup import Launcher

    launcher = Launcher(
        app, args.database, use_splash=not (args.no_splash or os.environ.get("DOCTORCAR_NO_SPLASH"))
    )
    launcher.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
