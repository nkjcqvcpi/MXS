"""Installed distribution version."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("MXS")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0.2.2"
