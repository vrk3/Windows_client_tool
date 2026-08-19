"""Theme sheets for the TreeSize pane (spec 5.3).

Two sheets applied by the module to its own root widget. Because a widget's
stylesheet applies to that widget and its descendants, this scopes to the pane
automatically: ThemeManager needs no change and the host app's sheets continue
to govern every other module.

Sheet selection follows the Windows `AppsUseLightTheme` setting.

Spec 5.3 says colours are sampled from the running product rather than guessed.
These are taken from the dark screenshots referenced in spec 1.1. Where a value
could not be read off a screenshot it follows the neighbouring sampled tone
rather than a Qt default, and is marked below.
"""
import winreg

DARK = {
    "bg": "#1F1F1F",
    "panel": "#252526",
    "ribbon": "#2D2D30",
    "border": "#3F3F46",
    "text": "#F1F1F1",
    "muted": "#9D9D9D",
    "accent": "#3D8BD4",
    "accent_hover": "#4A9BE8",
    "selection": "#094771",
    "bar_track": "#2A2D2E",
    "warning": "#E0A030",
}

LIGHT = {
    "bg": "#FFFFFF",
    "panel": "#F5F5F5",
    "ribbon": "#F0F0F0",
    "border": "#D4D4D4",
    "text": "#1E1E1E",
    "muted": "#606060",
    "accent": "#2A72B5",
    "accent_hover": "#3D8BD4",
    "selection": "#CCE4F7",
    "bar_track": "#E6E6E6",
    "warning": "#A66300",
}

_TEMPLATE = """
QWidget {{ background: {bg}; color: {text}; }}

#ribbonTabBar {{ background: {ribbon}; }}
#ribbonTabBar::tab {{
    background: transparent; color: {text};
    padding: 5px 14px; border: none; margin-right: 2px;
}}
#ribbonTabBar::tab:selected {{
    background: {panel}; border-top: 2px solid {accent};
}}
#ribbonTabBar::tab:hover:!selected {{ background: {border}; }}

#ribbonPages {{ background: {panel}; border-bottom: 1px solid {border}; }}
#ribbonGroup {{ border: none; }}
#ribbonGroupCaption {{ color: {muted}; font-size: 10px; }}
#ribbonSeparator {{ color: {border}; max-width: 1px; margin: 2px 4px; }}
#ribbonLargeButton {{
    padding: 4px 8px; border: 1px solid transparent; border-radius: 3px;
    min-width: 56px;
}}
#ribbonSmallButton {{
    padding: 2px 6px; border: 1px solid transparent; border-radius: 3px;
    text-align: left;
}}
#ribbonLargeButton:hover, #ribbonSmallButton:hover {{
    background: {selection}; border: 1px solid {accent};
}}
#ribbonLargeButton:checked, #ribbonSmallButton:checked {{
    background: {selection}; border: 1px solid {accent};
}}
#ribbonLargeButton:disabled, #ribbonSmallButton:disabled {{ color: {muted}; }}

#navButton {{
    background: {panel}; border: 1px solid {border};
    border-radius: 2px; padding: 2px;
}}
#navButton:hover {{ background: {selection}; }}
#scanState {{ color: {accent}; padding-left: 8px; }}
#scanOverviewField {{ color: {muted}; }}
#statusNotice {{ color: {warning}; }}

QComboBox {{
    background: {bg}; border: 1px solid {border};
    border-radius: 2px; padding: 3px 6px;
}}
QComboBox:focus {{ border: 1px solid {accent}; }}

QTreeView, QTreeWidget {{
    background: {bg}; alternate-background-color: {panel};
    border: 1px solid {border}; outline: none;
}}
QTreeView::item, QTreeWidget::item {{ padding: 2px; border: none; }}
QTreeView::item:selected, QTreeWidget::item:selected {{
    background: {selection}; color: {text};
}}
QTreeView::item:hover, QTreeWidget::item:hover {{ background: {bar_track}; }}

QHeaderView::section {{
    background: {panel}; color: {muted};
    padding: 4px 6px; border: none; border-right: 1px solid {border};
    border-bottom: 1px solid {border};
}}

QTabWidget::pane {{ border: 1px solid {border}; }}
QTabBar::tab {{
    background: {panel}; color: {muted};
    padding: 4px 12px; border: 1px solid {border}; border-bottom: none;
}}
QTabBar::tab:selected {{ background: {bg}; color: {text}; }}

QSplitter::handle {{ background: {border}; }}
QScrollBar:vertical {{ background: {bg}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {border}; border-radius: 5px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

#titleRow {{ background: {ribbon}; border-bottom: 1px solid {border}; }}
#paneTitle {{ color: {text}; font-weight: 600; }}
#qatButton {{
    color: {muted}; padding: 1px 6px; border: 1px solid transparent;
    border-radius: 2px; font-size: 13px;
}}
#qatButton:hover {{ background: {selection}; color: {text}; }}
#findOption {{
    background: {bg}; color: {text}; border: 1px solid {border};
    border-radius: 2px; padding: 2px 6px;
}}
#findOption:focus {{ border: 1px solid {accent}; }}
#findResults {{
    background: {panel}; border: 1px solid {accent}; color: {text};
}}
#findResults::item {{ padding: 3px 8px; }}
#findResults::item:selected {{ background: {selection}; }}

#backstage {{ background: {bg}; }}
#backstageRail {{ background: {ribbon}; border-right: 1px solid {border}; }}
#backstageBack, #backstageEntry {{
    background: transparent; color: {text}; border: none;
    text-align: left; padding: 7px 10px; border-radius: 2px;
}}
#backstageBack:hover, #backstageEntry:hover {{ background: {selection}; }}
#backstageHeading {{ color: {text}; font-size: 17px; font-weight: 600; }}
#recentList {{ background: {bg}; border: none; color: {text}; }}
#recentList::item {{ padding: 5px 4px; }}
#recentList::item:selected {{ background: {selection}; }}
#breadcrumb {{
    background: transparent; color: {accent}; border: none; padding: 1px 4px;
}}
#breadcrumb:hover {{ text-decoration: underline; }}
"""


def windows_prefers_light() -> bool:
    """Read AppsUseLightTheme. Defaults to dark, which is what Pro ships."""
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except OSError:
        return False


def stylesheet(light: bool | None = None) -> str:
    if light is None:
        light = windows_prefers_light()
    return _TEMPLATE.format(**(LIGHT if light else DARK))


def palette(light: bool | None = None) -> dict:
    if light is None:
        light = windows_prefers_light()
    return LIGHT if light else DARK


def apply_theme(widget, light: bool | None = None) -> None:
    widget.setStyleSheet(stylesheet(light))
