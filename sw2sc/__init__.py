"""sw2sc: clean-room SolidWorks to SolidCraft converter."""
import os as _os

try:
    with open(_os.path.join(_os.path.dirname(__file__), "..", "VERSION"), encoding="utf-8") as _f:
        __version__ = _f.read().strip()
except OSError:  # installed without the repo
    __version__ = "0.0.0"
