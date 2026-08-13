from __future__ import annotations

import struct

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from stepnx.authoring.metadata import MetadataDraft
from stepnx.core.profiles import (
    MetadataScope,
    ValueKind,
    authorable_metadata,
    metadata_definition,
    pack_dm120,
    pack_u16_range,
    unpack_dm120,
    unpack_u16_range,
)


class MetadataCollectionDialog(QDialog):
    """Ordered, duplicate-preserving metadata editor for one NX20 scope."""

    def __init__(
        self,
        drafts: tuple[MetadataDraft, ...],
        profile: str,
        scope: MetadataScope,
        parent=None,
        *,
        brain_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.scope = scope
        self.brain_only = brain_only
        self._drafts = list(drafts)
        self.setWindowTitle(
            "Brain Shower metadata" if brain_only else f"Edit {scope.value} metadata"
        )
        self.resize(820, 440)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Field", "Value", "Decoded", "Evidence", "Stable ID"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)

        add = QPushButton("Add…")
        edit = QPushButton("Edit value…")
        remove = QPushButton("Remove")
        up = QPushButton("Move up")
        down = QPushButton("Move down")
        add.clicked.connect(self._add)
        edit.clicked.connect(self._edit)
        remove.clicked.connect(self._remove)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        controls = QHBoxLayout()
        for button in (add, edit, remove, up, down):
            controls.addWidget(button)
        controls.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(controls)
        layout.addWidget(buttons)
        self._refresh()

    def drafts(self) -> tuple[MetadataDraft, ...]:
        return tuple(self._drafts)

    def _definition(self, draft: MetadataDraft):
        return metadata_definition(self.profile, self.scope, draft.meta_id)

    def _is_editable(self, draft: MetadataDraft) -> bool:
        definition = self._definition(draft)
        return bool(
            definition
            and definition.authorable
            and (not self.brain_only or definition.brain_shower)
        )

    def _refresh(self, selected: int | None = None) -> None:
        self.table.setRowCount(len(self._drafts))
        for row, draft in enumerate(self._drafts):
            definition = self._definition(draft)
            values = (
                str(draft.meta_id),
                definition.label if definition else "Unknown",
                str(draft.value),
                definition.display_value(draft.value)
                if definition
                else f"0x{draft.value:08X}",
                definition.evidence.value if definition else "unregistered",
                "new" if draft.stable_id is None else str(draft.stable_id),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if not self._is_editable(draft):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        if selected is not None and self._drafts:
            self.table.selectRow(max(0, min(selected, len(self._drafts) - 1)))

    def _candidate_definitions(self):
        candidates = authorable_metadata(self.profile, self.scope)
        if self.brain_only:
            candidates = tuple(item for item in candidates if item.brain_shower)
        return candidates

    def _add(self) -> None:
        definitions = self._candidate_definitions()
        labels = [f"{item.meta_id}: {item.label}" for item in definitions]
        if not labels:
            QMessageBox.information(
                self, "No fields", "This profile exposes no authorable fields here."
            )
            return
        label, accepted = QInputDialog.getItem(
            self, "Add metadata", "Field:", labels, 0, False
        )
        if not accepted:
            return
        definition = definitions[labels.index(label)]
        value = self._ask_value(definition, 0)
        if value is None:
            return
        self._drafts.append(MetadataDraft(definition.meta_id, value))
        self._refresh(len(self._drafts) - 1)

    def _edit(self, *args) -> None:
        row = self.table.currentRow()
        if not 0 <= row < len(self._drafts):
            return
        draft = self._drafts[row]
        definition = self._definition(draft)
        if not self._is_editable(draft):
            QMessageBox.information(
                self,
                "Raw field",
                "This entry is preserved but has no safe typed editor in the active profile.",
            )
            return
        value = self._ask_value(definition, draft.value)
        if value is None:
            return
        self._drafts[row] = MetadataDraft(draft.meta_id, value, draft.stable_id)
        self._refresh(row)

    def _remove(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._drafts) and self._is_editable(self._drafts[row]):
            del self._drafts[row]
            self._refresh(row)

    def _move(self, delta: int) -> None:
        row = self.table.currentRow()
        target = row + delta
        if (
            not 0 <= row < len(self._drafts)
            or not 0 <= target < len(self._drafts)
            or not self._is_editable(self._drafts[row])
            or not self._is_editable(self._drafts[target])
        ):
            return
        self._drafts[row], self._drafts[target] = (
            self._drafts[target],
            self._drafts[row],
        )
        self._refresh(target)

    def _ask_value(self, definition, current: int) -> int | None:
        if definition.kind is ValueKind.ENUM:
            labels = [f"{item.value}: {item.label}" for item in definition.choices]
            current_index = next(
                (
                    index
                    for index, item in enumerate(definition.choices)
                    if item.value == current
                ),
                0,
            )
            label, accepted = QInputDialog.getItem(
                self, definition.label, "Value:", labels, current_index, False
            )
            return definition.choices[labels.index(label)].value if accepted else None
        if definition.kind is ValueKind.PACKED_U16_RANGE:
            minimum, maximum = unpack_u16_range(current)
            text, accepted = QInputDialog.getText(
                self,
                definition.label,
                "Minimum..maximum (unsigned 16-bit):",
                text=f"{minimum}..{maximum}",
            )
            if not accepted:
                return None
            try:
                left, right = text.split("..", 1)
                return pack_u16_range(int(left, 0), int(right, 0))
            except (ValueError, TypeError) as exc:
                QMessageBox.critical(self, "Invalid range", str(exc))
                return None
        if definition.kind is ValueKind.PACKED_DM120:
            mode, weight = unpack_dm120(current)
            text, accepted = QInputDialog.getText(
                self,
                definition.label,
                "Mode/weight (mode 0 or 1; signed weight):",
                text=f"{mode}/{weight}",
            )
            if not accepted:
                return None
            try:
                left, right = text.split("/", 1)
                return pack_dm120(int(left, 0), int(right, 0))
            except (ValueError, TypeError) as exc:
                QMessageBox.critical(self, "Invalid DM120 value", str(exc))
                return None
        if definition.kind is ValueKind.FLOAT32_BITS:
            value = struct.unpack("<f", struct.pack("<I", current))[0]
            result, accepted = QInputDialog.getDouble(
                self,
                definition.label,
                "Float value:",
                value,
                -1_000_000_000.0,
                1_000_000_000.0,
                6,
            )
            return (
                struct.unpack("<I", struct.pack("<f", result))[0] if accepted else None
            )
        prompt = "Unsigned value (decimal or 0x hexadecimal):"
        if definition.kind is ValueKind.BITMASK and definition.bits:
            prompt += "\n" + ", ".join(
                f"0x{item.mask:X}={item.label}" for item in definition.bits
            )
        text, accepted = QInputDialog.getText(
            self, definition.label, prompt, text=str(current)
        )
        if not accepted:
            return None
        try:
            value = int(text, 0)
            if not 0 <= value <= 0xFFFFFFFF:
                raise ValueError("value must fit unsigned 32-bit storage")
            if definition.minimum is not None and value < definition.minimum:
                raise ValueError(f"value must be at least {definition.minimum}")
            if definition.maximum is not None and value > definition.maximum:
                raise ValueError(f"value must be at most {definition.maximum}")
            return value
        except ValueError as exc:
            QMessageBox.critical(self, "Invalid value", str(exc))
            return None
