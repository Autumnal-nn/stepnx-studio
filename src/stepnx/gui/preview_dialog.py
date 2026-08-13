from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)


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
        self.command_edit = QLineEdit(self)
        self.command_edit.setPlaceholderText("Optional COMMAND flags")

        form = QFormLayout()
        form.addRow("Chart (.NX):", self.chart_combo)
        form.addRow("Speed:", self.speed_combo)
        form.addRow("COMMAND:", self.command_edit)

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

    def options(self) -> PreviewLaunchOptions:
        document_index = self.chart_combo.currentData()
        if document_index is None:
            raise ValueError("no chart is available")
        return PreviewLaunchOptions(
            document_index=int(document_index),
            speed=int(self.speed_combo.currentData()),
            command=self.command_edit.text(),
        )
