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
    metadata_variant_label,
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
        self.resize(920, 460)

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

    def _patched_raw_scope(self) -> bool:
        return self.profile == "nxa-step5-patched" and self.scope in (
            MetadataScope.HEADER, MetadataScope.DIVISION
        )

    def _ask_raw_u32(self, title: str, current: int) -> int | None:
        from stepnx.gui.typed_inputs import RawU32Dialog
        dialog = RawU32Dialog(title, current, self)
        return dialog.value() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def _ask_unknown_patched_value(self, current: int) -> int | None:
        if self.scope is MetadataScope.HEADER:
            return self._ask_raw_u32("Raw Header value", current)
        from stepnx.gui.typed_inputs import PatchedUnknownDivisionDialog
        dialog = PatchedUnknownDivisionDialog(current, self)
        return dialog.value() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def _definition(self, draft: MetadataDraft):
        return metadata_definition(self.profile, self.scope, draft.meta_id)

    def _is_editable(self, draft: MetadataDraft) -> bool:
        if self._patched_raw_scope():
            return True
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
            variant = (
                metadata_variant_label(draft.meta_id)
                if self.scope is MetadataScope.HEADER
                else None
            )
            field = definition.label if definition else "Unknown"
            if variant:
                field = f"{field} [{variant}]"
            values = (
                str(draft.meta_id),
                field,
                str(draft.value),
                definition.display_value(draft.value)
                if definition
                else f"0x{draft.value:08X}",
                definition.evidence.value if definition else "unregistered",
                "new" if draft.stable_id is None else str(draft.stable_id),
            )
            tooltip = ""
            if definition:
                details = [definition.description] if definition.description else []
                if draft.meta_id > 0xFFFF and variant:
                    details.append(
                        f"Composite Header ID: base {draft.meta_id & 0xFFFF}, "
                        f"variant {draft.meta_id >> 16} ({variant}). The full 32-bit ID "
                        "is preserved when saving."
                    )
                tooltip = "\n\n".join(details)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if tooltip:
                    item.setToolTip(tooltip)
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
        if not labels and not self._patched_raw_scope():
            QMessageBox.information(
                self, "No fields", "This profile exposes no authorable fields here."
            )
            return
        if self._patched_raw_scope():
            labels.append("Custom raw ID...")
        label, accepted = QInputDialog.getItem(
            self, "Add metadata", "Field:", labels, 0, False
        )
        if not accepted:
            return
        if self._patched_raw_scope() and label == "Custom raw ID...":
            meta_id = self._ask_raw_u32("Raw metadata ID", 0)
            if meta_id is None:
                return
            definition = metadata_definition(self.profile, self.scope, meta_id)
            value = (
                self._ask_value(definition, 0)
                if definition else self._ask_unknown_patched_value(0)
            )
        else:
            definition = definitions[labels.index(label)]
            meta_id = definition.meta_id
            value = self._ask_value(definition, 0)
        if value is None:
            return
        self._drafts.append(MetadataDraft(meta_id, value))
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
        value = (
            self._ask_unknown_patched_value(draft.value)
            if definition is None and self._patched_raw_scope()
            else self._ask_value(definition, draft.value)
        )
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
        if self._patched_raw_scope():
            option, accepted = QInputDialog.getItem(
                self, definition.label, "Input representation:",
                ["Typed", "Raw uint32"], 0, False,
            )
            if not accepted:
                return None
            if option == "Raw uint32":
                return self._ask_raw_u32(definition.label, current)
        if definition.kind is ValueKind.ENUM:
            labels = [f"{item.value}: {item.label}" for item in definition.choices]
            current_index = next(
                (
                    index
                    for index, item in enumerate(definition.choices)
                    if item.value == current
                ),
                None,
            )
            if current_index is None:
                # Unknown enum values are legitimate data. Never replace one
                # implicitly with the first known choice.
                return self._ask_raw_u32(definition.label, current)
            label, accepted = QInputDialog.getItem(
                self, definition.label, "Value:", labels, current_index, False
            )
            return definition.choices[labels.index(label)].value if accepted else None
        if definition.kind in (ValueKind.PACKED_U16_RANGE, ValueKind.PACKED_DM120):
            from stepnx.gui.typed_inputs import PackedMetadataDialog

            if definition.kind is ValueKind.PACKED_U16_RANGE:
                first, second = unpack_u16_range(current)
                kind = "u16_range"
            else:
                first, second = unpack_dm120(current)
                kind = "dm120"
            try:
                dialog = PackedMetadataDialog(
                    definition.label, kind=kind, first=first, second=second, parent=self
                )
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Unsupported raw value",
                    "The stored value is outside the supported typed range. "
                    "It will be preserved unchanged.",
                )
                return None
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            first, second = dialog.values()
            return (
                pack_u16_range(first, second)
                if kind == "u16_range"
                else pack_dm120(first, second)
            )
        if definition.kind is ValueKind.INT32:
            value = struct.unpack("<i", struct.pack("<I", current))[0]
            result, accepted = QInputDialog.getInt(
                self,
                definition.label,
                "Signed 32-bit value:",
                value,
                -0x80000000,
                0x7FFFFFFF,
            )
            return result & 0xFFFFFFFF if accepted else None
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
        from stepnx.gui.typed_inputs import RawU32Dialog

        minimum = definition.minimum if definition.minimum is not None else 0
        maximum = definition.maximum if definition.maximum is not None else 0xFFFFFFFF
        if self._patched_raw_scope():
            minimum, maximum = 0, 0xFFFFFFFF
        # Existing out-of-range values are preserved and can still be edited
        # without changing the engine profile's advertised input bounds.
        if not minimum <= current <= maximum:
            return self._ask_raw_u32(definition.label, current)
        dialog = RawU32Dialog(
            definition.label, current, self, minimum=minimum, maximum=maximum
        )
        return dialog.value() if dialog.exec() == QDialog.DialogCode.Accepted else None
