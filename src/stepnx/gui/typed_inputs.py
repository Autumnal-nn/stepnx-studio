"""Reusable typed inputs for chart authoring dialogs.

UI controls do not change NX20 encodings: callers remain responsible for
applying a validated value through the existing command stack.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def rows_to_mbr(rows: int, beat_split: int, beat_measure: int) -> tuple[int, int, int]:
    if rows < 0 or beat_split <= 0 or beat_measure <= 0:
        raise ValueError("invalid row count or Block beat settings")
    beats, row = divmod(rows, beat_split)
    measure, beat = divmod(beats, beat_measure)
    return measure, beat, row


def mbr_to_rows(
    measure: int, beat: int, row: int, beat_split: int, beat_measure: int
) -> int:
    if beat_split <= 0 or beat_measure <= 0:
        raise ValueError("Block beat settings must be positive")
    if measure < 0 or not 0 <= beat < beat_measure or not 0 <= row < beat_split:
        raise ValueError("Measure/Beat/Row is outside its valid range")
    return (measure * beat_measure + beat) * beat_split + row


class MbrSpinRow(QWidget):
    """Measure, Beat and Row spin boxes; zero-based, matching legacy MBR."""

    def __init__(self, *, beat_split: int, beat_measure: int, parent=None) -> None:
        super().__init__(parent)
        if beat_split <= 0 or beat_measure <= 0:
            raise ValueError("Beat Split and Beat Measure must be positive")
        self.beat_split = int(beat_split)
        self.beat_measure = int(beat_measure)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.measure_spin = QSpinBox(self)
        self.beat_spin = QSpinBox(self)
        self.row_spin = QSpinBox(self)
        self.measure_spin.setRange(0, 2_147_483_647)
        self.beat_spin.setRange(0, beat_measure - 1)
        self.row_spin.setRange(0, beat_split - 1)
        for spin, label in (
            (self.measure_spin, "Measure"),
            (self.beat_spin, "Beat"),
            (self.row_spin, "Row"),
        ):
            spin.setAccessibleName(label)
            layout.addWidget(spin)
            layout.addWidget(QLabel(label, self))

    def set_from_rows(self, rows: int) -> None:
        measure, beat, row = rows_to_mbr(rows, self.beat_split, self.beat_measure)
        if measure > self.measure_spin.maximum():
            raise ValueError("row count exceeds the editor's supported range")
        self.measure_spin.setValue(measure)
        self.beat_spin.setValue(beat)
        self.row_spin.setValue(row)

    def value_tuple(self) -> tuple[int, int, int]:
        return (
            self.measure_spin.value(),
            self.beat_spin.value(),
            self.row_spin.value(),
        )

    def to_rows(self) -> int:
        return mbr_to_rows(*self.value_tuple(), self.beat_split, self.beat_measure)

    def setReadOnly(self, read_only: bool) -> None:
        for spin in (self.measure_spin, self.beat_spin, self.row_spin):
            spin.setReadOnly(read_only)
            spin.setButtonSymbols(
                QSpinBox.ButtonSymbols.NoButtons
                if read_only
                else QSpinBox.ButtonSymbols.UpDownArrows
            )


class LabeledRangeRow(QWidget):
    """Two independent numeric endpoints; no implicit sorting or clamping."""

    def __init__(
        self, *, minimum: int = 0, maximum: int = 65535, label: str = "", parent=None
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if label:
            layout.addWidget(QLabel(label, self))
        self.min_spin = QSpinBox(self)
        self.max_spin = QSpinBox(self)
        for spin, name in ((self.min_spin, "Minimum"), (self.max_spin, "Maximum")):
            spin.setRange(minimum, maximum)
            spin.setAccessibleName(name)
        layout.addWidget(self.min_spin)
        layout.addWidget(QLabel("-", self))
        layout.addWidget(self.max_spin)

    def set_values(self, minimum: int, maximum: int) -> None:
        for value, spin in ((minimum, self.min_spin), (maximum, self.max_spin)):
            if not spin.minimum() <= value <= spin.maximum():
                raise ValueError("range endpoint is outside supported storage")
        self.min_spin.setValue(minimum)
        self.max_spin.setValue(maximum)

    def values(self) -> tuple[int, int]:
        return self.min_spin.value(), self.max_spin.value()


class ResizeSplitDialog(QDialog):
    """Typed replacement for the legacy Measure|Beat|Row text prompt."""

    def __init__(
        self, current_rows: int, *, beat_split: int, beat_measure: int, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resize Split")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.from_row = MbrSpinRow(
            beat_split=beat_split, beat_measure=beat_measure, parent=self
        )
        self.from_row.set_from_rows(current_rows)
        self.from_row.setReadOnly(True)
        self.to_row = MbrSpinRow(
            beat_split=beat_split, beat_measure=beat_measure, parent=self
        )
        self.to_row.set_from_rows(current_rows)
        form.addRow("From:", self.from_row)
        form.addRow("To:", self.to_row)
        layout.addLayout(form)
        self.row_label = QLabel(self)
        layout.addWidget(self.row_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for spin in (
            self.to_row.measure_spin,
            self.to_row.beat_spin,
            self.to_row.row_spin,
        ):
            spin.valueChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_args) -> None:
        count = self.to_row.to_rows()
        self.row_label.setText(f"Requested rows: {count}")
        self._ok.setEnabled(count > 0)

    def requested_rows(self) -> int:
        count = self.to_row.to_rows()
        if count <= 0:
            raise ValueError("Split size must be greater than zero")
        return count
