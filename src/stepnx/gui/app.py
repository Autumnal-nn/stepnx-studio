from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _qt_import_error(exc: ImportError) -> int:
    print(
        "StepNX Studio's desktop UI requires the optional GUI dependencies. "
        "Install the project with: pip install -e '.[gui]'\n"
        f"Qt import failed: {exc}",
        file=sys.stderr,
    )
    return 2


def _run(folder: Path | None) -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QApplication,
            QFileDialog,
            QMainWindow,
            QMessageBox,
            QSplitter,
            QTableWidget,
            QTableWidgetItem,
            QTabWidget,
            QTreeWidget,
            QTreeWidgetItem,
        )
    except ImportError as exc:
        return _qt_import_error(exc)

    from stepnx.authoring import create_authoring_snapshot, load_visual_pack
    from stepnx.authoring.glyphs import VisualPackError
    from stepnx.gui.timeline_widget import TimelineWidget
    from stepnx.workspace import WorkspaceError, open_folder

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("StepNX Studio — Read-only viewport")
            self.resize(1440, 900)
            self.workspace = None
            self.pack = None
            self.tree = QTreeWidget()
            self.tree.setHeaderLabels(["Workspace", "Details"])
            self.tree.itemDoubleClicked.connect(self._tree_activated)
            self.tabs = QTabWidget()
            self.tabs.setTabsClosable(True)
            self.tabs.tabCloseRequested.connect(self.tabs.removeTab)
            self.side_tabs = QTabWidget()
            self.diagnostics = QTreeWidget()
            self.diagnostics.setHeaderLabels(["Severity", "Code", "Path", "Message"])
            self.inspector = QTableWidget(0, 4)
            self.inspector.setHorizontalHeaderLabels(["Scope / field", "ID", "Value", "Raw"])
            self.side_tabs.addTab(self.diagnostics, "Diagnostics")
            self.side_tabs.addTab(self.inspector, "Inspector")
            splitter = QSplitter()
            splitter.addWidget(self.tree)
            splitter.addWidget(self.tabs)
            splitter.addWidget(self.side_tabs)
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setStretchFactor(2, 0)
            self.setCentralWidget(splitter)

            file_menu = self.menuBar().addMenu("&File")
            file_menu.addAction("Open folder…", self._choose_folder)
            file_menu.addAction("Load local visual pack…", self._choose_pack)
            file_menu.addSeparator()
            file_menu.addAction("Exit", self.close)

        def _choose_folder(self) -> None:
            selected = QFileDialog.getExistingDirectory(self, "Open chart folder")
            if selected:
                self.load_folder(Path(selected))

        def _choose_pack(self) -> None:
            selected = QFileDialog.getExistingDirectory(self, "Select StepNX visual pack")
            if not selected:
                return
            try:
                self.pack = load_visual_pack(selected)
            except VisualPackError as exc:
                QMessageBox.critical(self, "Invalid visual pack", str(exc))
                return
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                if isinstance(widget, TimelineWidget):
                    widget.set_visual_pack(self.pack)
            self.statusBar().showMessage(f"Loaded local visual pack: {self.pack.name}", 5000)

        def load_folder(self, path: Path) -> None:
            try:
                self.workspace = open_folder(path)
            except (OSError, WorkspaceError) as exc:
                QMessageBox.critical(self, "Cannot open folder", str(exc))
                return
            self.setWindowTitle(f"StepNX Studio — {self.workspace.root.name} — Read-only")
            self.tabs.clear()
            self._populate_tree()
            self._populate_diagnostics()
            if self.workspace.documents:
                self._open_document(0)

        def _populate_tree(self) -> None:
            self.tree.clear()
            if self.workspace is None:
                return
            root = QTreeWidgetItem([self.workspace.root.name, str(self.workspace.root)])
            root.setData(0, Qt.ItemDataRole.UserRole, ("root", -1, -1, -1))
            self.tree.addTopLevelItem(root)
            for document_index, entry in enumerate(self.workspace.documents):
                document_item = QTreeWidgetItem([entry.path.name, entry.source_format.value])
                document_item.setData(0, Qt.ItemDataRole.UserRole, ("document", document_index, -1, -1))
                root.addChild(document_item)
                header = QTreeWidgetItem(["Header metadata", str(len(entry.document.header_metadata))])
                header.setData(0, Qt.ItemDataRole.UserRole, ("header", document_index, -1, -1))
                document_item.addChild(header)
                for split_index, split in enumerate(entry.document.splits):
                    split_item = QTreeWidgetItem(
                        [f"Split {split_index + 1}", f"{len(split.blocks)} block(s)"]
                    )
                    split_item.setData(0, Qt.ItemDataRole.UserRole, ("split", document_index, split_index, -1))
                    document_item.addChild(split_item)
                    for block_index, block in enumerate(split.blocks):
                        block_item = QTreeWidgetItem(
                            [f"Block {block_index + 1}", f"{len(block.rows)} rows"]
                        )
                        block_item.setData(0, Qt.ItemDataRole.UserRole, ("block", document_index, split_index, block_index))
                        split_item.addChild(block_item)
            for failure in self.workspace.failures:
                item = QTreeWidgetItem([failure.path.name, "Open failure"])
                item.setData(0, Qt.ItemDataRole.UserRole, ("failure", -1, -1, -1))
                root.addChild(item)
            root.setExpanded(True)

        def _populate_diagnostics(self) -> None:
            self.diagnostics.clear()
            if self.workspace is None:
                return
            for failure in self.workspace.failures:
                QTreeWidgetItem(self.diagnostics, ["error", "workspace.open", str(failure.path), failure.error])
            for diagnostic in self.workspace.diagnostics:
                QTreeWidgetItem(
                    self.diagnostics,
                    [diagnostic.severity.value, diagnostic.code, diagnostic.path, diagnostic.message],
                )
            for entry in self.workspace.documents:
                for issue in entry.validation.issues:
                    QTreeWidgetItem(
                        self.diagnostics,
                        [issue.severity.value, issue.code, f"{entry.path.name}:{issue.path}", issue.message],
                    )
            self.diagnostics.resizeColumnToContents(0)
            self.diagnostics.resizeColumnToContents(1)

        def _tree_activated(self, item, column) -> None:
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if not payload:
                return
            kind, document_index, split_index, block_index = payload
            if document_index >= 0:
                self._open_document(document_index)
                self._inspect(kind, document_index, split_index, block_index)

        def _open_document(self, document_index: int) -> None:
            entry = self.workspace.documents[document_index]
            for index in range(self.tabs.count()):
                if self.tabs.tabToolTip(index) == str(entry.path):
                    self.tabs.setCurrentIndex(index)
                    return
            snapshot = create_authoring_snapshot(entry.document)
            widget = TimelineWidget(snapshot)
            widget.set_visual_pack(self.pack)
            widget.inspectionRequested.connect(
                lambda split_id, block_id, doc=document_index: self._inspect_ids(doc, split_id, block_id)
            )
            index = self.tabs.addTab(widget, entry.path.name)
            self.tabs.setTabToolTip(index, str(entry.path))
            self.tabs.setCurrentIndex(index)

        def _inspect_ids(self, document_index: int, split_id: int, block_id: int) -> None:
            document = self.workspace.documents[document_index].document
            for split_index, split in enumerate(document.splits):
                if split.stable_id != split_id:
                    continue
                for block_index, block in enumerate(split.blocks):
                    if block.stable_id == block_id:
                        self._inspect("block", document_index, split_index, block_index)
                        return

        def _inspect(self, kind: str, document_index: int, split_index: int, block_index: int) -> None:
            document = self.workspace.documents[document_index].document
            rows: list[tuple[str, str, str, str]] = []
            if kind in ("document", "header"):
                rows.extend(
                    ("Header metadata", str(entry.meta_id.value), str(entry.value.value), entry.value.hex)
                    for entry in document.header_metadata
                )
            if kind == "split":
                split = document.splits[split_index]
                rows.extend(
                    ("Split metadata", str(entry.meta_id.value), str(entry.value.value), entry.value.hex)
                    for entry in split.metadata
                )
                rows.extend(
                    [
                        ("Raw select", "—", str(split.raw_select.value), split.raw_select.hex),
                        ("Raw brain", "—", str(split.raw_brain.value), split.raw_brain.hex),
                    ]
                )
            if kind == "block":
                block = document.splits[split_index].blocks[block_index]
                rows.extend(
                    [
                        ("BPM", "—", f"{block.bpm.value:g}", block.bpm.hex),
                        ("Scroll", "—", f"{block.scroll.value:g}", block.scroll.hex),
                        ("Beat split", "—", str(block.beat_split.value), block.beat_split.hex),
                        ("Beat measure", "—", str(block.beat_measure.value), block.beat_measure.hex),
                    ]
                )
                rows.extend(
                    ("Division metadata", str(entry.meta_id.value), str(entry.value.value), entry.value.hex)
                    for entry in block.divisions
                )
            self.inspector.setRowCount(len(rows))
            for row_index, values in enumerate(rows):
                for column_index, value in enumerate(values):
                    self.inspector.setItem(row_index, column_index, QTableWidgetItem(value))
            self.inspector.resizeColumnsToContents()
            self.side_tabs.setCurrentWidget(self.inspector)

    application = QApplication(sys.argv)
    application.setApplicationName("StepNX Studio")
    window = MainWindow()
    window.show()
    if folder is not None:
        window.load_folder(folder)
    return application.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the StepNX Studio read-only Qt viewport")
    parser.add_argument("folder", nargs="?", type=Path, help="chart folder to open")
    args = parser.parse_args(argv)
    return _run(args.folder)


if __name__ == "__main__":
    raise SystemExit(main())
