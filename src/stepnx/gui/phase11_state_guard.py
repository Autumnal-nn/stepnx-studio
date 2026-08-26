from __future__ import annotations


def install_phase11_state_guard(window) -> None:
    """Make transient Qt callbacks harmless while a folder is being reloaded.

    Deleting the currently selected chart can emit selection/tab signals between
    replacing ``sessions`` and rebuilding the tree. During that tiny interval a
    tree item may still carry the old document index. Metadata context is a
    read-only UI projection, so a stale index should mean "no context", not a
    traceback.
    """

    if getattr(window, "_phase11_state_guard_installed", False):
        return
    window._phase11_state_guard_installed = True

    original_metadata_context = window._metadata_context

    def safe_metadata_context():
        try:
            return original_metadata_context()
        except (KeyError, IndexError):
            return None

    window._metadata_context = safe_metadata_context
