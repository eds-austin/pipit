"""Application entry point: Qt setup, the dark theme and the QML main window."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from pipit import APP_ID, APP_NAME, __version__

QML_DIR = Path(__file__).resolve().parent / "ui" / "qml"
ICON_PATH = Path(__file__).resolve().parent / "ui" / "icons" / f"{APP_ID}.svg"
#: Every control is drawn from Pipit's own design tokens (ui/qml/Pipit), on top of
#: Qt Quick Controls' fully customizable Basic style, whatever the desktop style is.
STYLE = "Basic"
OVERLAYS = ("palette", "keys")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pipit", description=APP_NAME)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="load the UI, verify it started, then exit (used by tests/CI)",
    )
    parser.add_argument(
        "--install-desktop",
        action="store_true",
        help="add Pipit to the application menu for this user (for uv/pipx installs)",
    )
    parser.add_argument(
        "--uninstall-desktop", action="store_true", help="remove what --install-desktop added"
    )
    # Screenshot and test helpers.
    parser.add_argument("--screenshot", metavar="PNG", help=argparse.SUPPRESS)
    parser.add_argument("--screenshot-after", type=int, default=800, help=argparse.SUPPRESS)
    parser.add_argument("--size", default="", help=argparse.SUPPRESS)  # WxH, not maximized
    parser.add_argument("--screen", default="", help=argparse.SUPPRESS)
    parser.add_argument("--overlay", choices=OVERLAYS, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--palette-query", default="", help=argparse.SUPPRESS)
    parser.add_argument("--list", type=Path, default=None, help="open this Pipit list")
    parser.add_argument("--pack", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--today", default="", help=argparse.SUPPRESS)  # YYYY-MM-DD
    # Unknown args (e.g. Qt's -platform) are passed through to Qt.
    args, _unknown = parser.parse_known_args(argv)
    return args


def main(argv: Sequence[str] | None = None) -> int:  # noqa: PLR0915
    argv = list(sys.argv if argv is None else argv)
    args = _parse_args(argv[1:])
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.install_desktop or args.uninstall_desktop:
        from pipit import desktop_install

        changed = desktop_install.install() if args.install_desktop else desktop_install.uninstall()
        verb = "installed" if args.install_desktop else "removed"
        for path in changed:
            print(f"{verb} {path}")
        return 0

    # Qt is imported lazily so `--version`/`--help` work without a display.
    from datetime import date
    from tempfile import mkdtemp

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication

    from pipit.config.settings import AppSettings, load_settings
    from pipit.ui.backend.app_controller import AppController
    from pipit.ui.backend.checklist_backend import ChecklistBackend
    from pipit.ui.backend.entry_backend import EntryBackend
    from pipit.ui.backend.home_backend import HomeBackend
    from pipit.ui.backend.imports_backend import ImportsBackend
    from pipit.ui.backend.locations_backend import LocationsBackend
    from pipit.ui.backend.reports_backend import ReportsBackend
    from pipit.ui.backend.shell import Shell
    from pipit.ui.backend.species_backend import SpeciesBackend
    from pipit.ui.backend.theme import IconProvider, apply_theme
    from pipit.ui.backend.trips_backend import TripsBackend

    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationVersion(__version__)
    QApplication.setOrganizationName("Pipit")
    QApplication.setDesktopFileName(APP_ID)
    QQuickStyle.setStyle(STYLE)

    app = QApplication(argv)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    testing = bool(args.smoke_test or args.screenshot)
    # Tests and screenshots never read or write the user's settings file.
    settings = AppSettings() if testing else load_settings()
    mono = apply_theme(app, settings.ui_scale)

    shell = Shell(settings, save=lambda _settings: None) if testing else Shell(settings)
    if args.screen:
        shell.go(args.screen)
    if testing:
        controller = AppController(
            settings,
            save=lambda _settings: None,
            pack_path=args.pack,
            backups_root=Path(mkdtemp(prefix="pipit-backups-")),
            load_in_background=False,
        )
    else:
        controller = AppController(settings, pack_path=args.pack)
    if args.list is not None:
        controller.open_path(args.list)
    elif not testing:
        controller.reopen_last()
    entry = EntryBackend(controller, date.fromisoformat(args.today) if args.today else None)
    locations = LocationsBackend(controller)
    species = SpeciesBackend(controller)
    trips = TripsBackend(controller)
    checklist = ChecklistBackend(controller)
    reports = ReportsBackend(controller)
    home = HomeBackend(controller)
    imports = ImportsBackend(controller)

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))
    icons = IconProvider()
    engine.addImageProvider("icon", icons)
    context = engine.rootContext()
    context.setContextProperty("pipitMonoFamily", mono)
    context.setContextProperty("pipitUiScale", settings.ui_scale)
    context.setContextProperty("shell", shell)
    context.setContextProperty("app", controller)
    context.setContextProperty("entry", entry)
    context.setContextProperty("locations", locations)
    context.setContextProperty("species", species)
    context.setContextProperty("trips", trips)
    context.setContextProperty("checklist", checklist)
    context.setContextProperty("reports", reports)
    context.setContextProperty("home", home)
    context.setContextProperty("imports", imports)
    engine.setInitialProperties({"appVersion": __version__, "maximized": not args.size})
    engine.warnings.connect(
        lambda warnings: [print(w.toString(), file=sys.stderr) for w in warnings]
    )
    engine.load(QML_DIR / "Main.qml")
    if not engine.rootObjects():
        print("error: failed to load the QML user interface", file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]
    if args.size:
        width, _, height = args.size.partition("x")
        window.setProperty("width", int(width))
        window.setProperty("height", int(height))

    if args.overlay:
        from PySide6.QtCore import Q_ARG, QMetaObject

        overlay = args.overlay
        query = args.palette_query
        QTimer.singleShot(
            200,
            lambda: QMetaObject.invokeMethod(
                window, "openOverlay", Q_ARG("QVariant", overlay), Q_ARG("QVariant", query)
            ),
        )

    if args.smoke_test:
        QTimer.singleShot(0, app.quit)
        code = int(app.exec())
        print(f"smoke-test ok: style={QQuickStyle.name()}")
        return code

    if args.screenshot:
        output = Path(args.screenshot)

        def shoot() -> None:
            window.grabWindow().save(str(output))
            app.quit()

        QTimer.singleShot(args.screenshot_after, shoot)

    code = int(app.exec())
    del icons, engine
    return code


if __name__ == "__main__":
    raise SystemExit(main())
