"""Fonts, the Qt palette and the tinted-icon image provider.

The colours here mirror ``qml/Pipit/Theme.qml`` (the design tokens); the QPalette
makes Basic-style popups, tooltips and scroll bars follow the dark theme too.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPalette
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONT_UI = "Inter"
FONT_NUM = "JetBrains Mono"
BODY_PX = 13  # at scale 1.0; multiplied by the ui_scale setting

TOKENS = {
    "bg": "#0E1116",
    "surface": "#151A21",
    "surface2": "#1B222C",
    "surface3": "#232B37",
    "border": "#2A3340",
    "borderStrong": "#3A4555",
    "text": "#E6EDF3",
    "textMuted": "#8B97A6",
    "textFaint": "#5D6876",
    "textOnAccent": "#0B0E12",
    "accent": "#4C9AFF",
    "positive": "#2FBF71",
    "negative": "#F2545B",
    "warning": "#E3B341",
    "info": "#9A8CFF",
}


def load_fonts() -> tuple[str, str]:
    """Register the bundled fonts; (ui family, mono family) with system fallbacks."""
    loaded: set[str] = set()
    for ttf in sorted((ASSETS / "fonts").glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(ttf))
        if fid < 0:
            log.warning("could not load font %s", ttf.name)
            continue
        loaded.update(QFontDatabase.applicationFontFamilies(fid))
    ui = (
        FONT_UI
        if FONT_UI in loaded
        else QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    )
    mono = (
        FONT_NUM
        if FONT_NUM in loaded
        else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    )
    return ui, mono


def apply_theme(app: QApplication, scale: float = 1.0) -> str:
    """App font and palette. Returns the monospace family for QML."""
    ui, mono = load_fonts()
    font = QFont(ui)
    font.setPixelSize(round(BODY_PX * scale))
    app.setFont(font)
    t = TOKENS
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: t["bg"],
        QPalette.ColorRole.WindowText: t["text"],
        QPalette.ColorRole.Base: t["surface"],
        QPalette.ColorRole.AlternateBase: t["surface"],
        QPalette.ColorRole.Text: t["text"],
        QPalette.ColorRole.Button: t["surface2"],
        QPalette.ColorRole.ButtonText: t["text"],
        QPalette.ColorRole.Highlight: t["accent"],
        QPalette.ColorRole.HighlightedText: t["textOnAccent"],
        QPalette.ColorRole.ToolTipBase: t["surface3"],
        QPalette.ColorRole.ToolTipText: t["text"],
        QPalette.ColorRole.PlaceholderText: t["textFaint"],
        QPalette.ColorRole.Link: t["accent"],
        QPalette.ColorRole.Mid: t["border"],
        QPalette.ColorRole.Dark: t["bg"],
        QPalette.ColorRole.Light: t["surface3"],
    }
    for role, c in roles.items():
        pal.setColor(role, QColor(c))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["textFaint"]))
    app.setPalette(pal)
    return mono


@functools.cache
def _svg(name: str) -> str | None:
    path = ASSETS / "icons" / f"{name}.svg"
    if not path.is_file() or "/" in name or ".." in name:
        return None
    return path.read_text(encoding="utf-8")


class IconProvider(QQuickImageProvider):
    """``image://icon/<lucide-name>/<RRGGBB>``: the icon in that colour."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, id_: str, size: QSize, requested: QSize) -> QImage:
        name, _, color = id_.partition("/")
        color = color.split("?")[0] or TOKENS["textMuted"].lstrip("#")
        src = _svg(name)
        w = requested.width() if requested.width() > 0 else 36
        h = requested.height() if requested.height() > 0 else w
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        if src is not None:
            # Lucide strokes are 2px at 24px; 1.75 reads calmer at UI sizes.
            data = src.replace("currentColor", f"#{color[:6]}").replace(
                'stroke-width="2"', 'stroke-width="1.75"'
            )
            renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(p, QRectF(0, 0, w, h))
            p.end()
        size.setWidth(w)
        size.setHeight(h)
        return img
