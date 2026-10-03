"""GS Capture for Maya 2027. No third-party Python packages required."""

__version__ = "0.1.0"


def show():
    from .ui import show as show_panel
    return show_panel()
