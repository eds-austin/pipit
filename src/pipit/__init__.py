"""Pipit: a fast, keyboard-first bird list for the Linux desktop."""

from importlib.metadata import PackageNotFoundError, version

APP_NAME = "Pipit"
APP_ID = "io.github.pipit.Pipit"
APP_SLUG = "pipit"

try:
    __version__ = version("pipit")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0+unknown"

__all__ = ["APP_ID", "APP_NAME", "APP_SLUG", "__version__"]
