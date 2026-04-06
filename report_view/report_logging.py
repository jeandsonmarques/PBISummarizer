from datetime import datetime

try:
    from qgis.core import Qgis, QgsMessageLog
except Exception:  # pragma: no cover - allows pure-python smoke tests
    class Qgis:
        Info = "INFO"
        Warning = "WARNING"
        Critical = "CRITICAL"

    class QgsMessageLog:
        @staticmethod
        def logMessage(message, tag, level=None):
            return None

try:
    from ..utils.runtime_paths import runtime_state_file
except ImportError:  # pragma: no cover - supports running report_view as a top-level package
    from utils.runtime_paths import runtime_state_file


LOG_CHANNEL = "PowerBI Summarizer"
LOG_FILE = runtime_state_file("relatorios_debug.log")


def _append_file_log(level_name: str, message: str):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat()} [{level_name}] {message}\n")
    except Exception:
        pass


def log_info(message: str):
    QgsMessageLog.logMessage(str(message), LOG_CHANNEL, level=Qgis.Info)
    _append_file_log("INFO", str(message))


def log_warning(message: str):
    QgsMessageLog.logMessage(str(message), LOG_CHANNEL, level=Qgis.Warning)
    _append_file_log("WARNING", str(message))


def log_error(message: str):
    QgsMessageLog.logMessage(str(message), LOG_CHANNEL, level=Qgis.Critical)
    _append_file_log("ERROR", str(message))
