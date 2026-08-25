from __future__ import annotations

import unittest

from stepnx.gui.phase11_profile_gate import (
    available_profiles,
    default_profile,
    executable_enables_patched_profile,
    install_phase11_profile_gate,
)


class _FakeAction:
    def __init__(self, *, checked: bool = False) -> None:
        self._checked = checked
        self.visible = True
        self.text = ""
        self.peer = None

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        self._checked = checked
        if checked and self.peer is not None:
            self.peer._checked = False

    def setVisible(self, visible: bool) -> None:
        self.visible = visible

    def setText(self, text: str) -> None:
        self.text = text


class _FakeWindow:
    def __init__(self, *, patched_checked: bool = False) -> None:
        native = _FakeAction(checked=not patched_checked)
        patched = _FakeAction(checked=patched_checked)
        native.peer = patched
        patched.peer = native
        self.profile_actions = {
            "nxa-native": native,
            "fiesta2": _FakeAction(),
            "prime2": _FakeAction(),
            "nxa-step5-patched": patched,
        }


class Phase11ProfileGateTests(unittest.TestCase):
    def test_easter_egg_name_is_exact(self) -> None:
        self.assertTrue(executable_enables_patched_profile("StepMX Studio.exe"))
        self.assertFalse(executable_enables_patched_profile("stepmx studio.exe"))
        self.assertFalse(executable_enables_patched_profile("StepMX-Studio.exe"))
        self.assertFalse(executable_enables_patched_profile("StepNX Studio.exe"))

    def test_normal_profile_catalog_contains_only_public_choices(self) -> None:
        self.assertEqual(
            available_profiles("StepNX Studio.exe"),
            ("nxa-native", "fiesta2", "prime2"),
        )
        self.assertEqual(default_profile("StepNX Studio.exe"), "nxa-native")

    def test_stepmx_catalog_replaces_native_nxa_with_patched(self) -> None:
        self.assertEqual(
            available_profiles("StepMX Studio.exe"),
            ("nxa-step5-patched", "fiesta2", "prime2"),
        )
        self.assertEqual(
            default_profile("StepMX Studio.exe"), "nxa-step5-patched"
        )

    def test_normal_executable_hides_patched_and_keeps_native(self) -> None:
        window = _FakeWindow()
        install_phase11_profile_gate(window, executable_name="StepNX Studio.exe")
        native = window.profile_actions["nxa-native"]
        patched = window.profile_actions["nxa-step5-patched"]
        self.assertTrue(native.visible)
        self.assertTrue(native.isChecked())
        self.assertEqual(native.text, "NXA")
        self.assertFalse(patched.visible)
        self.assertFalse(patched.isChecked())
        self.assertEqual(patched.text, "NXA-patched")
        self.assertFalse(window.phase11_patched_profile_enabled)

    def test_stepmx_replaces_native_with_patched_as_default(self) -> None:
        window = _FakeWindow()
        install_phase11_profile_gate(window, executable_name="StepMX Studio.exe")
        native = window.profile_actions["nxa-native"]
        patched = window.profile_actions["nxa-step5-patched"]
        self.assertEqual(native.text, "NXA")
        self.assertFalse(native.visible)
        self.assertFalse(native.isChecked())
        self.assertTrue(patched.visible)
        self.assertTrue(patched.isChecked())
        self.assertEqual(patched.text, "NXA-patched")
        self.assertTrue(window.phase11_patched_profile_enabled)

    def test_normal_executable_recovers_from_hidden_patched_cli_selection(self) -> None:
        window = _FakeWindow(patched_checked=True)
        install_phase11_profile_gate(window, executable_name="anything.exe")
        self.assertTrue(window.profile_actions["nxa-native"].isChecked())
        self.assertFalse(window.profile_actions["nxa-step5-patched"].isChecked())


if __name__ == "__main__":
    unittest.main()
