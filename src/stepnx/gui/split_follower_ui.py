from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from stepnx.authoring.semantics import project_routes
from stepnx.authoring.split_selection import SplitSelectionByte


def route_mode_label(route) -> str:
    """Return the canonical user-facing selector label for a projected Split."""

    return SplitSelectionByte(
        random_at_start=bool(route.random_at_start),
        random_at_trigger=bool(route.random_at_trigger),
        force_select=bool(route.force_select),
        bank=int(route.group),
    ).mode_label


def populate_routes(window) -> None:
    """Populate Routes without legacy random-trigger/group terminology.

    The old UI rendered the pre-audit names first and then rewrote strings in a
    second pass. Keep one source of truth instead: SplitSelectionByte owns the
    selector wording, while the route projection owns conditions/triggers.
    """

    window.routes.clear()
    if window.workspace is None:
        return

    for document_index, entry in enumerate(window.workspace.documents):
        document = window.sessions[document_index].current
        document_item = QTreeWidgetItem(
            window.routes,
            [entry.path.name, document.profile, "", ""],
        )
        for route in project_routes(document):
            split_item = QTreeWidgetItem(
                document_item,
                [
                    f"Split {route.split_index + 1}",
                    route_mode_label(route),
                    "",
                    "",
                ],
            )
            split_item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                ("route", document_index, route.split_id, None),
            )
            for branch in route.branches:
                conditions = "; ".join(
                    f"{item.metric} {item.minimum}..{item.maximum}"
                    for item in branch.conditions
                )
                triggers = ", ".join(
                    f"r{item.row_index + 1}/c{item.column + 1}:D{item.division_id}"
                    + ("*" if item.triggers else "")
                    for item in branch.triggers[:8]
                )
                if len(branch.triggers) > 8:
                    triggers += f", +{len(branch.triggers) - 8}"
                branch_item = QTreeWidgetItem(
                    split_item,
                    [
                        f"Block {branch.block_index + 1}",
                        "candidate",
                        conditions or "unconditional",
                        triggers or "none",
                    ],
                )
                branch_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    ("route", document_index, route.split_id, branch.block_id),
                )
        document_item.setExpanded(True)


def install_split_follower_ui(window) -> None:
    """Keep Routes terminology aligned with selector timing/bank semantics."""

    if getattr(window, "_stepnx_split_follower_ui", False):
        return
    window._stepnx_split_follower_ui = True
    window._populate_routes = lambda: populate_routes(window)
    populate_routes(window)
