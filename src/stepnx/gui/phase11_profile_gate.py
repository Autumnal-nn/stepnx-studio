from __future__ import annotations

import sys
from pathlib import Path


_PATCHED_EXECUTABLE_NAME = "StepMX Studio.exe"
_STANDARD_PROFILES = ("nxa-native", "fiesta2", "prime2")
_PATCHED_PROFILES = ("nxa-step5-patched", "fiesta2", "prime2")


def executable_enables_patched_profile(executable_name: str | None = None) -> bool:
    """Return whether the deliberately hidden patched-NXA profile is exposed.

    The comparison is intentionally exact. Normal StepNX Studio builds expose
    only native NXA, Fiesta 2, and Prime 2. Renaming the Windows executable to
    the easter-egg name replaces native NXA with the patched profile.
    """

    if executable_name is None:
        executable_name = Path(sys.argv[0]).name
    else:
        executable_name = Path(executable_name).name
    return executable_name == _PATCHED_EXECUTABLE_NAME


def available_profiles(executable_name: str | None = None) -> tuple[str, ...]:
    return (
        _PATCHED_PROFILES
        if executable_enables_patched_profile(executable_name)
        else _STANDARD_PROFILES
    )


def default_profile(executable_name: str | None = None) -> str:
    return available_profiles(executable_name)[0]


def install_phase11_profile_gate(window, *, executable_name: str | None = None) -> None:
    actions = getattr(window, "profile_actions", None)
    if not isinstance(actions, dict):
        return

    native = actions.get("nxa-native")
    patched = actions.get("nxa-step5-patched")
    if native is None or patched is None:
        return

    native.setText("NXA")
    patched.setText("NXA-patched")
    enabled = executable_enables_patched_profile(executable_name)

    if enabled:
        was_native = native.isChecked()
        native.setVisible(False)
        patched.setVisible(True)
        if was_native:
            patched.setChecked(True)
    else:
        was_patched = patched.isChecked()
        patched.setVisible(False)
        native.setVisible(True)
        if was_patched:
            native.setChecked(True)

    window.phase11_patched_profile_enabled = enabled
