import os
from typing import List, Optional

from qgis.PyQt.QtGui import QFont, QFontDatabase

_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "fonts", "Inter")
_FONT_FILES = (
    "Inter-Regular.ttf",
    "Inter-Medium.ttf",
    "Inter-SemiBold.ttf",
    "Inter-Bold.ttf",
)
_REGISTERED_FAMILIES: Optional[List[str]] = None


def ensure_ui_fonts_registered() -> List[str]:
    global _REGISTERED_FAMILIES
    if _REGISTERED_FAMILIES is not None:
        return list(_REGISTERED_FAMILIES)

    families: List[str] = []
    for filename in _FONT_FILES:
        path = os.path.join(_FONT_DIR, filename)
        if not os.path.exists(path):
            continue
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id == -1:
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family and family not in families:
                families.append(family)

    _REGISTERED_FAMILIES = families
    return list(_REGISTERED_FAMILIES)


def ui_font_family(default: str = "Inter") -> str:
    families = ensure_ui_fonts_registered()
    return families[0] if families else default


def ui_font_stack() -> str:
    family = ui_font_family()
    return f'"{family}", sans-serif'


def ui_font(point_size: Optional[int] = None, weight: int = QFont.Normal) -> QFont:
    font = QFont(ui_font_family())
    if point_size is not None:
        font.setPointSize(point_size)
    font.setWeight(weight)
    return font
