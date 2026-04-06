"""
Centralized color and typography definitions for the PowerBISummarizer plugin.

The palette closely follows Power BI / Excel styling guidelines so the rest
of the codebase can import consistent tokens instead of hardcoding values.
"""

from collections import ChainMap

COLORS = {
    "color_app_bg": "#FAFAFA",
    "color_surface": "#FFFFFF",
    "color_border": "#E2E6EC",
    "color_text_primary": "#1E1E1E",
    "color_text_secondary": "#4B5563",
    "color_primary": "#F2C811",
    "color_primary_hover": "#D6A800",
    "color_secondary": "#2B7DE9",
    "color_success": "#2FB26A",
    "color_warning": "#F2994A",
    "color_error": "#EB5757",
    "color_table_zebra": "#F6F8FB",
    "color_table_selection": "#FFF4CC",
    "color_splitter": "#E2E6EC",
    "color_shadow": "rgba(17, 24, 39, 0.06)",
}

TYPOGRAPHY = {
    "font_family": "Segoe UI",
    "font_ui_stack": '"Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue", Arial, sans-serif',
    "font_mono_stack": '"Cascadia Mono", "SF Mono", Consolas, "Liberation Mono", monospace',
    "font_base_size": 11,
    "font_title_size": 18,
    "font_subtitle_size": 14,
    "font_section_size": 13,
    "font_body_size": 11,
    "font_small_size": 10,
    "font_page_title_px": 24,
    "font_section_title_px": 16,
    "font_body_px": 13,
    "font_secondary_px": 12,
    "font_caption_px": 11,
    "font_button_px": 13,
    "font_chip_px": 12,
    "font_weight_regular": 400,
    "font_weight_medium": 500,
    "font_weight_semibold": 600,
}

MISC = {
    "radius_surface": 12,
    "radius_button": 10,
    "radius_input": 8,
    "radius_table": 10,
    "button_height": 36,
    "input_height": 32,
    "tab_height": 36,
}


def palette_context():
    """
    Helper that merges all dictionaries so template formatting can use
    the keys as `${color_app_bg}`, `${font_title_size}`, etc.
    """

    return ChainMap({}, COLORS, TYPOGRAPHY, MISC)
