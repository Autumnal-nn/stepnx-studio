from __future__ import annotations


def main(argv=None) -> int:
    # app._run imports these classes lazily. Install the extended authoring
    # adapters before delegating to the base application entry point.
    try:
        from PySide6.QtWidgets import QMainWindow
    except ImportError:
        from stepnx.gui.app import main as base_main
        return base_main(argv)

    import stepnx.gui.timeline_widget as timeline_module
    import stepnx.gui.timing_dialog as timing_module
    import stepnx.gui.preview_widget as preview_module
    from stepnx.gui.phase10_install import install_phase10
    from stepnx.gui.phase10_timeline import Phase10TimelineWidget
    from stepnx.gui.phase10_timing import Phase10BlockTimingDialog
    from stepnx.gui.phase10_preview import Phase10GameplayPreviewWidget
    from stepnx.gui.phase11_import import install_phase11_import
    from stepnx.gui.phase11_workspace import install_phase11_workspace_tools

    timeline_module.TimelineWidget = Phase10TimelineWidget
    timing_module.BlockTimingDialog = Phase10BlockTimingDialog
    preview_module.GameplayPreviewWidget = Phase10GameplayPreviewWidget

    original_show = QMainWindow.show

    def show_with_phase10(self, *args, **kwargs):
        if self.windowTitle() == "StepNX Studio":
            install_phase10(self)
            install_phase11_import(self)
            install_phase11_workspace_tools(self)
        return original_show(self, *args, **kwargs)

    QMainWindow.show = show_with_phase10
    try:
        from stepnx.gui.app import main as base_main
        return base_main(argv)
    finally:
        QMainWindow.show = original_show
