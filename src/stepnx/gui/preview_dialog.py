from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from stepnx.preview.commands import COMMAND_FLAGS, serialize_command_flags


@dataclass(frozen=True, slots=True)
class PreviewChartChoice:
    document_index: int
    filename: str


@dataclass(frozen=True, slots=True)
class PreviewLaunchOptions:
    document_index: int
    speed: int
    command: str


class GameplayInitializationDialog(QDialog):
    """Collect every gameplay-launch option in one deliberately small dialog."""

    _EXCLUSIVE_COMMAND_PEERS = {
        "d": "a",
        "a": "d",
        "s": "e",
        "e": "s",
        "(": ")",
        ")": "(",
    }

    def __init__(
        self,
        charts: tuple[PreviewChartChoice, ...],
        *,
        current_document_index: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not charts:
            raise ValueError("gameplay initialization requires a playable NX chart")
        self.setWindowTitle("Gameplay initialization")

        current = next(
            (
                chart
                for chart in charts
                if chart.document_index == current_document_index
            ),
            charts[0],
        )
        self.chart_combo = QComboBox(self)
        for chart in charts:
            self.chart_combo.addItem(chart.filename, chart.document_index)
        selected = self.chart_combo.findData(current.document_index)
        if selected >= 0:
            self.chart_combo.setCurrentIndex(selected)

        self.speed_combo = QComboBox(self)
        for speed in range(1, 10):
            self.speed_combo.addItem(f"{speed}x", speed)

        self.command_list = QListWidget(self)
        # Keep the complete semantic modifier set visible. A 250px list hid the
        # final entries on common Windows font metrics and looked like missing flags.
        self.command_list.setMinimumHeight(max(250, len(COMMAND_FLAGS) * 22))
        self.command_items: dict[str, QListWidgetItem] = {}
        for flag in COMMAND_FLAGS:
            # Historical PIUTESTER command characters remain an internal
            # compatibility key. The Studio presents the semantic modifier name.
            item = QListWidgetItem(flag.label)
            item.setData(Qt.ItemDataRole.UserRole, flag.code)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.command_list.addItem(item)
            self.command_items[flag.code] = item
        self.command_list.itemChanged.connect(self._command_item_changed)

        form = QFormLayout()
        form.addRow("Chart (.NX):", self.chart_combo)
        form.addRow("Speed:", self.speed_combo)
        form.addRow("Preview modifiers:", self.command_list)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

    def _command_item_changed(self, item: QListWidgetItem) -> None:
        if item.checkState() is not Qt.CheckState.Checked:
            return
        code = str(item.data(Qt.ItemDataRole.UserRole))
        peer = self._EXCLUSIVE_COMMAND_PEERS.get(code)
        if peer is None:
            return
        peer_item = self.command_items[peer]
        if peer_item.checkState() is Qt.CheckState.Checked:
            peer_item.setCheckState(Qt.CheckState.Unchecked)

    def selected_command_codes(self) -> tuple[str, ...]:
        return tuple(
            flag.code
            for flag in COMMAND_FLAGS
            if self.command_items[flag.code].checkState() is Qt.CheckState.Checked
        )

    def options(self) -> PreviewLaunchOptions:
        document_index = self.chart_combo.currentData()
        if document_index is None:
            raise ValueError("no chart is available")
        return PreviewLaunchOptions(
            document_index=int(document_index),
            speed=int(self.speed_combo.currentData()),
            command=serialize_command_flags(self.selected_command_codes()),
        )
