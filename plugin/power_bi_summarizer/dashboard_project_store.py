from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from qgis.PyQt.QtCore import QSettings

from .dashboard_models import DashboardProject


RECENTS_SETTINGS_KEY = "PowerBISummarizer/model/recent_projects"
LAST_DIR_SETTINGS_KEY = "PowerBISummarizer/model/last_dir"
PROJECT_EXTENSION = ".pbsdash"
MAX_RECENTS = 8


class DashboardProjectStore:
    def __init__(self):
        self.settings = QSettings()

    def default_directory(self) -> str:
        configured = self.settings.value(LAST_DIR_SETTINGS_KEY, "", type=str)
        if configured and os.path.isdir(configured):
            return configured
        documents = os.path.join(os.path.expanduser("~"), "Documents")
        target = os.path.join(documents, "Summarizer", "Dashboards")
        try:
            os.makedirs(target, exist_ok=True)
        except Exception:
            return documents if os.path.isdir(documents) else os.path.expanduser("~")
        return target

    def normalize_path(self, path: str) -> str:
        cleaned = os.path.abspath(os.path.expanduser(str(path or "").strip()))
        if not cleaned.lower().endswith(PROJECT_EXTENSION):
            cleaned += PROJECT_EXTENSION
        return cleaned

    def save_project(self, path: str, project: DashboardProject) -> str:
        final_path = self.normalize_path(path)
        directory = os.path.dirname(final_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        payload = project.to_dict()
        with open(final_path, "w", encoding="utf-8") as handler:
            json.dump(payload, handler, ensure_ascii=False, indent=2)

        self.settings.setValue(LAST_DIR_SETTINGS_KEY, directory or self.default_directory())
        self.record_recent_project(final_path, project.name)
        return final_path

    def load_project(self, path: str) -> DashboardProject:
        final_path = self.normalize_path(path)
        with open(final_path, "r", encoding="utf-8") as handler:
            payload = json.load(handler)
        project = DashboardProject.from_dict(payload)
        for page in list(project.pages or []):
            try:
                normalized_page = page.normalized()
                page.page_id = normalized_page.page_id
                page.title = normalized_page.title
                page.items = [item.clone() for item in list(normalized_page.items or [])]
                page.visual_links = [item for item in list(normalized_page.visual_links or [])]
                page.chart_relations = [item for item in list(normalized_page.chart_relations or [])]
                page.zoom = float(normalized_page.zoom or 1.0)
                page.filters = dict(normalized_page.filters or {})
            except Exception:
                continue
        for item in list(project.items or []):
            try:
                binding = item.binding.normalized()
                if not binding.chart_id:
                    binding.chart_id = item.item_id
                item.binding = binding
            except Exception:
                continue
        self.settings.setValue(LAST_DIR_SETTINGS_KEY, os.path.dirname(final_path))
        self.record_recent_project(final_path, project.name)
        return project

    def load_recents(self) -> List[Dict[str, Any]]:
        raw_value = self.settings.value(RECENTS_SETTINGS_KEY, "", type=str)
        if not raw_value:
            return []
        try:
            items = json.loads(raw_value)
        except Exception:
            return []
        results: List[Dict[str, Any]] = []
        for item in list(items or []):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            if not os.path.exists(path):
                continue
            results.append(
                {
                    "path": path,
                    "name": str(item.get("name") or os.path.splitext(os.path.basename(path))[0]),
                    "updated_at": str(item.get("updated_at") or ""),
                }
            )
        if len(results) != len(list(items or [])):
            self._save_recents(results)
        return results[:MAX_RECENTS]

    def record_recent_project(self, path: str, name: Optional[str] = None):
        final_path = self.normalize_path(path)
        recents = [item for item in self.load_recents() if item.get("path") != final_path]
        recents.insert(
            0,
            {
                "path": final_path,
                "name": str(name or os.path.splitext(os.path.basename(final_path))[0]),
                "updated_at": datetime.now().isoformat(),
            },
        )
        self._save_recents(recents[:MAX_RECENTS])

    def clear_recents(self):
        self._save_recents([])

    def _save_recents(self, items: List[Dict[str, Any]]):
        try:
            self.settings.setValue(RECENTS_SETTINGS_KEY, json.dumps(items, ensure_ascii=False))
        except Exception:
            self.settings.setValue(RECENTS_SETTINGS_KEY, "[]")
