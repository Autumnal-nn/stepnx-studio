from __future__ import annotations

import unittest

try:
    from stepnx.gui.phase11_import import _close_workspace
except ImportError as exc:
    _close_workspace = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


class _Clearable:
    def __init__(self) -> None:
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True


class _Inspector:
    def __init__(self) -> None:
        self.rows = 3

    def setRowCount(self, rows: int) -> None:
        self.rows = rows


class _Action:
    def __init__(self) -> None:
        self.enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class _Transport:
    def __init__(self) -> None:
        self.loaded = object()

    def load(self, source) -> None:
        self.loaded = source


class _StatusBar:
    def __init__(self) -> None:
        self.message = ""

    def showMessage(self, message: str, _duration: int) -> None:
        self.message = message


class _Window:
    def __init__(self) -> None:
        self.workspace = object()
        self.sessions = {1: object()}
        self.baselines = {1: object()}
        self.widget_documents = {1: object()}
        self.preview_snapshots = {1: object()}
        self.gesture_keys = {1: object()}
        self.tabs = _Clearable()
        self.tree = _Clearable()
        self.diagnostics = _Clearable()
        self.routes = _Clearable()
        self.inspector = _Inspector()
        self.waveform = object()
        self.metronome_clock = object()
        self.note_metronome_clock = object()
        self.audio_transport = _Transport()
        self.profile_actions = {
            "nxa-native": _Action(),
            "fiesta2": _Action(),
            "prime2": _Action(),
        }
        self.title = "StepNX Studio — TEST"
        self._status = _StatusBar()

    def _confirm_discard(self) -> bool:
        return True

    def setWindowTitle(self, title: str) -> None:
        self.title = title

    def statusBar(self):
        return self._status


@unittest.skipIf(
    _close_workspace is None,
    f"Qt runtime unavailable: {QT_UNAVAILABLE}",
)
class Phase11CloseFolderTests(unittest.TestCase):
    def test_close_folder_restores_application_level_ui_state(self) -> None:
        window = _Window()
        self.assertTrue(_close_workspace(window))

        self.assertIsNone(window.workspace)
        self.assertIsNone(window.audio_transport.loaded)
        self.assertEqual(window.title, "StepNX Studio")
        self.assertTrue(all(action.enabled for action in window.profile_actions.values()))
        self.assertEqual(window.inspector.rows, 0)
        self.assertTrue(window.tabs.cleared)
        self.assertTrue(window.tree.cleared)
        self.assertIsNone(window.waveform)
        self.assertIsNone(window.metronome_clock)
        self.assertIsNone(window.note_metronome_clock)
        self.assertEqual(window._status.message, "Closed chart folder")


if __name__ == "__main__":
    unittest.main()
