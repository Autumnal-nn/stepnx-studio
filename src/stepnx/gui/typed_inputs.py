"""Reusable typed inputs for chart authoring dialogs.

UI controls do not change NX20 encodings: callers remain responsible for
applying a validated value through the existing command stack.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QLineEdit,
    QCheckBox,
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


class PackedMetadataDialog(QDialog):
    """Edit a packed metadata field without string parsing or silent coercion."""

    def __init__(self, title: str, *, kind: str, first: int, second: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.kind = kind
        layout = QVBoxLayout(self)
        form = QFormLayout()
        if kind == "u16_range":
            self.range_row = LabeledRangeRow(minimum=0, maximum=0xFFFF, parent=self)
            self.range_row.set_values(first, second)
            form.addRow("Minimum / Maximum:", self.range_row)
        elif kind == "dm120":
            if first not in (0, 1) or second < (-1 if first == 0 else -2) or second > 255:
                raise ValueError("DM120 value cannot be represented by the typed editor")
            self.mode = QComboBox(self)
            self.mode.addItem("0", 0)
            self.mode.addItem("1", 1)
            self.mode.setCurrentIndex(first)
            self.weight = QSpinBox(self)
            self.weight.setRange(-2, 255)
            self.weight.setValue(second)
            form.addRow("Mode:", self.mode)
            form.addRow("Weight:", self.weight)
            self.mode.currentIndexChanged.connect(self._refresh_dm120)
            self.weight.valueChanged.connect(self._refresh_dm120)
        else:
            raise ValueError(f"unsupported packed metadata kind: {kind}")
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if kind == "dm120":
            self._refresh_dm120()

    def _refresh_dm120(self, *_args):
        minimum = -1 if self.mode.currentData() == 0 else -2
        self._ok_button.setEnabled(self.weight.value() >= minimum)
        self.weight.setToolTip(
            f"Mode {self.mode.currentData()} supports weights {minimum}..255"
        )

    def values(self) -> tuple[int, int]:
        if self.kind == "u16_range":
            return self.range_row.values()
        return int(self.mode.currentData()), self.weight.value()


class RawU32Dialog(QDialog):
    """Exact uint32 entry, including hexadecimal and undocumented bit patterns."""

    def __init__(self, title: str, value: int, parent=None):
        super().__init__(parent)
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("value must be uint32")
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.raw_edit = QLineEdit(f"0x{value:08X}", self)
        self.raw_edit.setAccessibleName("Raw unsigned 32-bit value")
        form.addRow("Value (hex or decimal):", self.raw_edit)
        layout.addLayout(form)
        self.error_label = QLabel(self)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.raw_edit.textChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_args):
        try:
            self.value()
        except ValueError:
            self.error_label.setText("Enter an unsigned 32-bit integer.")
            self._ok.setEnabled(False)
        else:
            self.error_label.setText("")
            self._ok.setEnabled(True)

    def value(self) -> int:
        text = self.raw_edit.text().strip()
        if not text:
            raise ValueError("empty value")
        value = int(text, 0) if text.lower().startswith(("0x", "0b", "0o")) else int(text, 10)
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("value must fit unsigned 32-bit storage")
        return value


class PatchedUnknownDivisionDialog(QDialog):
    """Unknown Division metadata defaults to two packed uint16 endpoints."""

    def __init__(self, value: int, parent=None):
        super().__init__(parent)
        from stepnx.core.profiles import unpack_u16_range

        self.setWindowTitle("Unknown Division value")
        layout = QVBoxLayout(self)
        self.range_row = LabeledRangeRow(minimum=0, maximum=0xFFFF, parent=self)
        self.range_row.set_values(*unpack_u16_range(value))
        layout.addWidget(self.range_row)
        self.raw_mode = QCheckBox("Edit as raw uint32 instead", self)
        layout.addWidget(self.raw_mode)
        self.raw_edit = QLineEdit(f"0x{value:08X}", self)
        self.raw_edit.setEnabled(False)
        layout.addWidget(self.raw_edit)
        self.validation = QLabel(self)
        layout.addWidget(self.validation)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.raw_mode.toggled.connect(self._mode_changed)
        self.raw_edit.textChanged.connect(self._validate)
        self._validate()

    def _mode_changed(self, raw: bool):
        self.range_row.setEnabled(not raw)
        self.raw_edit.setEnabled(raw)
        self._validate()

    def _validate(self, *_args):
        if not self.raw_mode.isChecked():
            self._ok.setEnabled(True)
            self.validation.setText("")
            return
        try:
            self.value()
        except ValueError:
            self.validation.setText("Enter an unsigned 32-bit integer.")
            self._ok.setEnabled(False)
        else:
            self.validation.setText("")
            self._ok.setEnabled(True)

    def value(self) -> int:
        from stepnx.core.profiles import pack_u16_range
        if not self.raw_mode.isChecked():
            return pack_u16_range(*self.range_row.values())
        raw = self.raw_edit.text().strip()
        if not raw:
            raise ValueError("empty value")
        value = int(raw, 0) if raw.lower().startswith(("0x", "0b", "0o")) else int(raw, 10)
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("value must fit unsigned 32-bit storage")
        return value
