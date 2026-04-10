import logging
import queue
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

LOG_DIR = Path.home() / "Library" / "Logs" / "NetWatch"
LOG_FILE = LOG_DIR / "netwatch.log"

# Log levels mapped to UI colors
LEVEL_COLORS = {
    "INFO":    "#94A3B8",   # slate
    "WARNING": "#F59E0B",   # amber
    "ERROR":   "#EF4444",   # red
    "SUCCESS": "#22C55E",   # green
    "ACTION":  "#60A5FA",   # blue
    "FIX":     "#A78BFA",   # purple
}


class NetWatchLogger:
    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.ui_queue: queue.Queue = queue.Queue()
        self._setup_file_logger()

    def _setup_file_logger(self):
        self._logger = logging.getLogger("netwatch")
        self._logger.setLevel(logging.DEBUG)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s",
                              datefmt="%Y-%m-%d %H:%M:%S")
        )
        self._logger.addHandler(handler)

    def _emit(self, level: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        # Write to file
        getattr(self._logger, level.lower(), self._logger.info)(message)
        # Push to UI queue
        self.ui_queue.put({
            "timestamp": timestamp,
            "level": level,
            "message": message,
            "color": LEVEL_COLORS.get(level, "#94A3B8"),
        })

    def info(self, msg: str):    self._emit("INFO", msg)
    def warning(self, msg: str): self._emit("WARNING", msg)
    def error(self, msg: str):   self._emit("ERROR", msg)
    def success(self, msg: str): self._emit("SUCCESS", msg)
    def action(self, msg: str):  self._emit("ACTION", msg)
    def fix(self, msg: str):     self._emit("FIX", msg)

    @property
    def log_path(self) -> Path:
        return LOG_FILE
