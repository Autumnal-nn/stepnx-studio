from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from stepnx.authoring.timing import BlockTimingValues


class BlockTimingDialog(QDialog):
    """Typed editor for the exact nine scalar fields stored by an NX20 Block."""

    def __init__(
        self,
        values: BlockTimingValues,
        parent=None,
        *,
        previous_end_ms: float | None = None,
        advanced: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Block timing")
        self._previous_end_ms = None if advanced else previous_end_ms
        shown_start = (
            values.start_time_ms
            if self._previous_end_ms is None
            else values.start_time_ms - self._previous_end_ms
        )
        self._start = self._float(shown_start, decimals=4)
        self._bpm = self._float(values.bpm, minimum=0.0001, decimals=6)
        self._scroll = self._float(values.scroll_factor, decimals=6)
        self._offset = self._float(values.offset_or_delay_ms, decimals=4)
        self._speed = self._float(values.speed, minimum=0.0, decimals=6)
        self._split = self._integer(values.beat_split, 1, 255)
        self._measure = self._integer(values.beat_measure, 1, 255)
        self._smooth = self._integer(values.smooth_speed, 0, 255)
        self._flag = self._integer(values.raw_flag, 0, 255)
        self._freeze = QCheckBox("Freeze/stop Block (negative Speed)")
        self._freeze.setChecked(values.is_freeze)
        self._smooth_transition = QCheckBox("Smooth scroll transition (nonzero byte)")
        self._smooth_transition.setChecked(values.smooth_speed != 0)
        self._real_scroll = QLabel()

        form = QFormLayout()
        form.addRow(
            "Start Time (ms)" if self._previous_end_ms is None else "Gap after previous Block (ms)",
            self._start,
        )
        form.addRow("BPM", self._bpm)
        form.addRow("Scroll Factor", self._scroll)
        form.addRow("Real Scroll", self._real_scroll)
        form.addRow("Offset / Delay (ms)", self._offset)
        form.addRow("Speed", self._speed)
        form.addRow("", self._freeze)
        form.addRow("Beat Split", self._split)
        form.addRow("Beat Measure", self._measure)
        form.addRow("Smooth Speed byte", self._smooth)
        form.addRow("", self._smooth_transition)
        form.addRow("Raw Flag", self._flag)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._scroll.valueChanged.connect(self._refresh_real_scroll)
        self._split.valueChanged.connect(self._refresh_real_scroll)
        self._smooth.valueChanged.connect(self._read_smooth_value)
        self._smooth_transition.toggled.connect(self._write_smooth_value)
        self._refresh_real_scroll()

    @staticmethod
    def _float(
        value: float, *, minimum: float = -1_000_000_000.0, decimals: int = 4
    ) -> QDoubleSpinBox:
        editor = QDoubleSpinBox()
        editor.setDecimals(decimals)
        editor.setRange(minimum, 1_000_000_000.0)
        editor.setValue(value)
        editor.setKeyboardTracking(False)
        return editor

    @staticmethod
    def _integer(value: int, minimum: int, maximum: int) -> QSpinBox:
        editor = QSpinBox()
        editor.setRange(minimum, maximum)
        editor.setValue(value)
        editor.setKeyboardTracking(False)
        return editor

    def _refresh_real_scroll(self, *args) -> None:
        self._real_scroll.setText(f"{self._scroll.value() * self._split.value():g}")

    def _read_smooth_value(self, *args) -> None:
        raw = self._smooth.value()
        self._smooth_transition.blockSignals(True)
        self._smooth_transition.setChecked(raw != 0)
        self._smooth_transition.blockSignals(False)

    def _write_smooth_value(self, *args) -> None:
        raw = self._smooth.value()
        if self._smooth_transition.isChecked():
            raw = raw or 1
        else:
            raw = 0
        self._smooth.blockSignals(True)
        self._smooth.setValue(raw)
        self._smooth.blockSignals(False)

    def values(self) -> BlockTimingValues:
        speed = self._speed.value()
        if self._freeze.isChecked():
            speed = -speed
        return BlockTimingValues(
            self._start.value() + (self._previous_end_ms or 0.0),
            self._bpm.value(),
            self._scroll.value(),
            self._offset.value(),
            speed,
            self._split.value(),
            self._measure.value(),
            self._smooth.value(),
            self._flag.value(),
        )
