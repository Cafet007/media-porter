"""
Central theme — modern flat design, dark and light mode.
Inspired by macOS Sonoma / SF Design System.
"""


class Theme:
    """Mutable theme singleton. Call T.set_dark(bool) then apply_theme() on widgets."""

    def __init__(self, dark: bool = False):
        self.dark = dark
        self._load()

    def set_dark(self, dark: bool) -> None:
        self.dark = dark
        self._load()

    def _load(self) -> None:
        if self.dark:
            self.BG_BASE       = "#0d0d0d"
            self.BG_PANEL      = "#141414"
            self.BG_SIDEBAR    = "#111111"
            self.BG_HEADER     = "#111111"
            self.BG_CARD       = "#1e1e20"
            self.BG_CARD_SEL   = "#0a2d5e"
            self.BG_TABLE      = "#0d0d0d"
            self.BG_TABLE_ALT  = "#111111"
            self.BG_TABLE_HDR  = "#0d0d0d"
            self.BG_INPUT      = "#1c1c1e"
            self.BG_BOTTOM     = "#111111"
            self.BG_SEGMENT    = "#1c1c1e"
            self.SEG_ACTIVE    = "#3a3a3c"
            self.SEG_ACTIVE_TXT = "#f0f0f0"

            self.BORDER        = "#2c2c2e"
            self.BORDER_FOCUS  = "#0a84ff"
            self.BORDER_CARD   = "#2a2a2c"
            self.BORDER_CARD_SEL = "#0a84ff"

            self.TEXT_PRIMARY   = "#f0f0f0"
            self.TEXT_SECONDARY = "#8e8e93"
            self.TEXT_MUTED     = "#48484a"
            self.TEXT_LABEL     = "#aeaeb2"

            self.ACCENT         = "#0a84ff"
            self.ACCENT_HOVER   = "#409cff"
            self.SUCCESS        = "#30d158"
            self.WARNING        = "#ff9f0a"
            self.DANGER         = "#ff453a"
            self.CONFLICT       = "#ff9f0a"

            self.SPLITTER       = "#1e1e1e"
            self.DIVIDER        = "#1e1e1e"

            self._PROGRESS_BG          = "#1e1e1e"
            self._TAB_HOVER_BG         = "#2c2c2e"
            self._HEADER_SECTION_HOVER = "#111111"
        else:
            self.BG_BASE       = "#f2f2f7"
            self.BG_PANEL      = "#ffffff"
            self.BG_SIDEBAR    = "#f2f2f7"
            self.BG_HEADER     = "#f9f9fb"
            self.BG_CARD       = "#ffffff"
            self.BG_CARD_SEL   = "#dceeff"
            self.BG_TABLE      = "#ffffff"
            self.BG_TABLE_ALT  = "#f9f9fb"
            self.BG_TABLE_HDR  = "#f2f2f7"
            self.BG_INPUT      = "#ffffff"
            self.BG_BOTTOM     = "#f2f2f7"
            self.BG_SEGMENT    = "#e5e5ea"
            self.SEG_ACTIVE    = "#ffffff"
            self.SEG_ACTIVE_TXT = "#000000"

            self.BORDER        = "#e5e5ea"
            self.BORDER_FOCUS  = "#007aff"
            self.BORDER_CARD   = "#e5e5ea"
            self.BORDER_CARD_SEL = "#007aff"

            self.TEXT_PRIMARY   = "#1c1c1e"
            self.TEXT_SECONDARY = "#3c3c43"
            self.TEXT_MUTED     = "#aeaeb2"
            self.TEXT_LABEL     = "#3c3c43"

            self.ACCENT         = "#007aff"
            self.ACCENT_HOVER   = "#3395ff"
            self.SUCCESS        = "#34c759"
            self.WARNING        = "#ff9f0a"
            self.DANGER         = "#ff3b30"
            self.CONFLICT       = "#ff9f0a"

            self.SPLITTER       = "#e5e5ea"
            self.DIVIDER        = "#e5e5ea"

            self._PROGRESS_BG          = "#e5e5ea"
            self._TAB_HOVER_BG         = "#ebebf0"
            self._HEADER_SECTION_HOVER = "#ebebf0"

    # -----------------------------------------------------------------------
    # Composite styles
    # -----------------------------------------------------------------------

    @property
    def TOOLBAR_STYLE(self) -> str:
        return f"""
            QWidget#mainToolbar {{
                background: {self.BG_HEADER};
                border-bottom: 1px solid {self.DIVIDER};
            }}
        """

    # legacy alias kept for any widget still referencing it
    @property
    def HEADER_STYLE(self) -> str:
        return self.TOOLBAR_STYLE

    @property
    def ACTIONBAR_STYLE(self) -> str:
        return f"""
            QWidget#actionBar {{
                background: {self.BG_BOTTOM};
                border-top: 1px solid {self.DIVIDER};
            }}
        """

    @property
    def SEGMENT_STYLE(self) -> str:
        return f"""
            QWidget#segContainer {{
                background: {self.BG_SEGMENT};
                border-radius: 9px;
            }}
            QWidget#segContainer QPushButton {{
                background: transparent;
                border: none;
                border-radius: 7px;
                color: {self.TEXT_MUTED};
                font-size: 13px;
                font-weight: 600;
                min-width: 82px;
                padding: 0 8px;
            }}
            QWidget#segContainer QPushButton:checked {{
                background: {self.SEG_ACTIVE};
                color: {self.SEG_ACTIVE_TXT};
            }}
            QWidget#segContainer QPushButton:hover:!checked {{
                color: {self.TEXT_SECONDARY};
            }}
        """

    @property
    def PANEL_TITLE_STYLE(self) -> str:
        return (
            f"color: {self.TEXT_MUTED}; font-size: 10px; "
            f"font-weight: 700; letter-spacing: 1.5px;"
        )

    @property
    def INPUT_STYLE(self) -> str:
        return f"""
            QLineEdit {{
                background: {self.BG_INPUT};
                border: 1.5px solid {self.BORDER};
                border-radius: 8px;
                padding: 7px 11px;
                color: {self.TEXT_PRIMARY};
                font-size: 13px;
                min-height: 36px;
            }}
            QLineEdit:focus {{ border: 1.5px solid {self.BORDER_FOCUS}; }}
        """

    @property
    def TABLE_STYLE(self) -> str:
        return f"""
            QTableWidget {{
                background: {self.BG_TABLE};
                alternate-background-color: {self.BG_TABLE_ALT};
                color: {self.TEXT_PRIMARY};
                font-size: 13px;
                border: none;
                gridline-color: transparent;
                selection-background-color: {self.BG_CARD_SEL};
                selection-color: {self.TEXT_PRIMARY};
            }}
            QHeaderView::section {{
                background: {self.BG_TABLE_HDR};
                color: {self.TEXT_MUTED};
                font-size: 10px;
                font-weight: 700;
                padding: 8px 12px;
                border: none;
                border-bottom: 1px solid {self.DIVIDER};
                letter-spacing: 1px;
            }}
            QHeaderView::section:hover {{
                background: {self._HEADER_SECTION_HOVER};
                color: {self.TEXT_SECONDARY};
            }}
            QTableWidget::item {{
                padding: 5px 12px;
                color: {self.TEXT_PRIMARY};
                border: none;
            }}
            QTableWidget::item:selected {{
                background: {self.BG_CARD_SEL};
                color: {self.TEXT_PRIMARY};
            }}
            QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {self.BORDER}; border-radius: 4px; min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {self.TEXT_MUTED}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar:horizontal {{ background: transparent; height: 8px; }}
            QScrollBar::handle:horizontal {{ background: {self.BORDER}; border-radius: 4px; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        """

    @property
    def PROGRESS_STYLE(self) -> str:
        return f"""
            QProgressBar {{
                background: {self._PROGRESS_BG}; border: none; border-radius: 4px;
            }}
            QProgressBar::chunk {{ background: {self.ACCENT}; border-radius: 4px; }}
        """

    @property
    def FILE_PROGRESS_STYLE(self) -> str:
        return f"""
            QProgressBar {{
                background: {self.BORDER}; border-radius: 2px; border: none;
            }}
            QProgressBar::chunk {{ background: {self.SUCCESS}; border-radius: 2px; }}
        """

    # -----------------------------------------------------------------------
    # Button styles
    # -----------------------------------------------------------------------

    def btn_primary(self, h: int = 36) -> str:
        r = min(h // 2, 18)
        return f"""
            QPushButton {{
                background: {self.ACCENT}; border: none; border-radius: {r}px;
                color: white; font-size: 13px; font-weight: 600;
                padding: 0 20px; min-height: {h}px;
            }}
            QPushButton:hover {{ background: {self.ACCENT_HOVER}; }}
            QPushButton:pressed {{ background: #0060df; }}
            QPushButton:disabled {{ background: {self.BORDER}; color: {self.TEXT_MUTED}; }}
        """

    def btn_secondary(self, h: int = 36) -> str:
        r = min(h // 2, 18)
        if self.dark:
            return f"""
                QPushButton {{
                    background: #2c2c2e; border: none; border-radius: {r}px;
                    color: {self.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;
                    padding: 0 16px; min-height: {h}px;
                }}
                QPushButton:hover {{ background: #3a3a3c; }}
                QPushButton:pressed {{ background: #1c1c1e; }}
                QPushButton:disabled {{ background: #1e1e1e; color: {self.TEXT_MUTED}; }}
            """
        return f"""
            QPushButton {{
                background: #e5e5ea; border: none; border-radius: {r}px;
                color: {self.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;
                padding: 0 16px; min-height: {h}px;
            }}
            QPushButton:hover {{ background: #d1d1d6; }}
            QPushButton:pressed {{ background: #c7c7cc; }}
            QPushButton:disabled {{ background: #e5e5ea; color: {self.TEXT_MUTED}; }}
        """

    def btn_danger(self, h: int = 36) -> str:
        r = min(h // 2, 18)
        return f"""
            QPushButton {{
                background: {self.DANGER}; border: none; border-radius: {r}px;
                color: white; font-size: 13px; font-weight: 600;
                padding: 0 16px; min-height: {h}px;
            }}
            QPushButton:hover {{ background: {'#ff6961' if self.dark else '#ff6b6b'}; }}
            QPushButton:pressed {{ background: #cc1e15; }}
            QPushButton:disabled {{ background: {self.BORDER}; color: {self.TEXT_MUTED}; }}
        """

    def small_btn_style(self) -> str:
        if self.dark:
            return f"""
                QPushButton {{
                    background: #2c2c2e; border: none; border-radius: 7px;
                    color: {self.TEXT_SECONDARY}; font-size: 12px; font-weight: 600;
                    padding: 0 10px; min-height: 26px;
                }}
                QPushButton:hover {{ background: #3a3a3c; color: {self.TEXT_PRIMARY}; }}
            """
        return f"""
            QPushButton {{
                background: #e5e5ea; border: none; border-radius: 7px;
                color: {self.TEXT_SECONDARY}; font-size: 12px; font-weight: 600;
                padding: 0 10px; min-height: 26px;
            }}
            QPushButton:hover {{ background: #d1d1d6; color: {self.TEXT_PRIMARY}; }}
        """


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
T = Theme()

# ---------------------------------------------------------------------------
# Module-level aliases (backward compat)
# ---------------------------------------------------------------------------
BG_BASE = T.BG_BASE; BG_PANEL = T.BG_PANEL; BG_HEADER = T.BG_HEADER
BG_CARD = T.BG_CARD; BG_CARD_SEL = T.BG_CARD_SEL; BG_TABLE = T.BG_TABLE
BG_TABLE_ALT = T.BG_TABLE_ALT; BG_TABLE_HDR = T.BG_TABLE_HDR
BG_INPUT = T.BG_INPUT; BG_BOTTOM = T.BG_BOTTOM
BORDER = T.BORDER; BORDER_FOCUS = T.BORDER_FOCUS
BORDER_CARD = T.BORDER_CARD; BORDER_CARD_SEL = T.BORDER_CARD_SEL
TEXT_PRIMARY = T.TEXT_PRIMARY; TEXT_SECONDARY = T.TEXT_SECONDARY
TEXT_MUTED = T.TEXT_MUTED; TEXT_LABEL = T.TEXT_LABEL
ACCENT = T.ACCENT; ACCENT_HOVER = T.ACCENT_HOVER
SUCCESS = T.SUCCESS; WARNING = T.WARNING; DANGER = T.DANGER; CONFLICT = T.CONFLICT
SPLITTER = T.SPLITTER; DIVIDER = T.DIVIDER
PANEL_TITLE_STYLE = T.PANEL_TITLE_STYLE
INPUT_STYLE = T.INPUT_STYLE; TABLE_STYLE = T.TABLE_STYLE


def btn_primary(h: int = 36) -> str: return T.btn_primary(h=h)
def btn_secondary(h: int = 36) -> str: return T.btn_secondary(h)
def btn_danger(h: int = 36) -> str: return T.btn_danger(h)
