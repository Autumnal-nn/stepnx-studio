from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from stepnx.authoring import create_authoring_snapshot
    from stepnx.codecs.nx20 import parse_bytes
    from stepnx.gui.timeline_widget import TimelineWidget
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""

from tests.fixture_factory import make_large_lightmap


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class QtViewportSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_offscreen_widget_culls_and_renders_large_chart(self) -> None:
        document = parse_bytes(make_large_lightmap(), source="LM.NX", row_storage="compact")
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(900, 640)
            widget.show()
            self.application.processEvents()

            self.assertGreater(widget.verticalScrollBar().maximum(), 1_000_000)
            image = QImage(widget.size(), QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            try:
                widget.render(painter, QPoint())
            finally:
                painter.end()
            self.assertNotEqual(image.pixelColor(10, 10).rgba(), 0)
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
