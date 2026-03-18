try:
    from .reports_widget import ReportsWidget
except Exception:  # pragma: no cover - allows pure-python smoke tests without QGIS
    ReportsWidget = None

__all__ = ["ReportsWidget"]
