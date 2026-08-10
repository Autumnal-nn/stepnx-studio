"""StepNX Studio's NX20 core.

The package is intentionally independent from Qt.  A chart codec that needs a
GUI event loop to prove it preserves bytes would already be broken.
"""

from stepnx.codecs.nx20 import load, parse_bytes, save_atomic, serialize

__all__ = ["load", "parse_bytes", "save_atomic", "serialize"]
__version__ = "0.1.0.dev0"

