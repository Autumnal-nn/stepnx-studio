from __future__ import annotations

from dataclasses import replace

from stepnx.gui.timing_dialog import BlockTimingDialog as _BaseBlockTimingDialog


class Phase10BlockTimingDialog(_BaseBlockTimingDialog):
    """Keep later absolute Start Time behind the advanced-timing switch.

    In normal mode a later Block is adjusted through Offset / Delay. Its
    absolute Start Time is intentionally hidden, not merely disabled, so the
    Edit > Show advanced Split timing toggle has an obvious visual effect.
    """

    def __init__(self, values, parent=None) -> None:
        self._phase10_original_start = values.start_time_ms
        self._phase10_lock_start = False
        advanced = bool(getattr(parent, "phase10_show_advanced_timing", False))
        context = None
        if parent is not None:
            resolver = getattr(parent, "_phase10_timing_context", None)
            if callable(resolver):
                context = resolver()
        if context is not None and not context.get("is_first", False) and not advanced:
            self._phase10_lock_start = True

        super().__init__(values, parent)
        form = self.layout().itemAt(0).layout()
        if form is not None:
            offset_label = form.labelForField(self._offset)
            if offset_label is not None:
                offset_label.setText("Offset / Delay (ms)")

        if self._phase10_lock_start:
            # Hide the advanced field completely in normal authoring. Keeping it
            # visible-but-disabled made the mode switch appear to do nothing.
            self._start.setEnabled(False)
            self._start.hide()
            if form is not None:
                label = form.labelForField(self._start)
                if label is not None:
                    label.hide()
            self.setWindowTitle("Edit Block timing")
        elif context is not None and not context.get("is_first", False):
            self._start.setToolTip("Absolute Start Time (advanced Split timing)")

    def values(self):
        values = super().values()
        if not self._phase10_lock_start:
            return values
        return replace(values, start_time_ms=self._phase10_original_start)
