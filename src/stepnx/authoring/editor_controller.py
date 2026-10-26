"""Qt-independent editing state and command adapter for the STEPEdit workflow.

This is an opt-in foundation: existing GUI editing paths are unchanged.
Actual hold, toggle and resize semantics remain owned by their current services
until they can be extracted without breaking the fast-note path.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from enum import Enum

from stepnx.authoring.selection import CellSelection, CellTarget
from stepnx.authoring.snapshot import AuthoringSnapshot, create_authoring_snapshot
from stepnx.core.commands import Command, CommandStack, NoteEdit, SetNoteAt, SetNotesAt
from stepnx.core.model import CompactRows, EmptyRow, LightmapRow, NoteRow, OverlayRows, PackedNoteRow


class EditorContextError(ValueError):
    """An action refers to a different document, branch, or cell."""


class InteractionProfile(str, Enum):
    STUDIO = "studio"
    STEPEDIT_CLASSIC = "stepedit-classic"


class InteractionTool(str, Enum):
    TOGGLE = "toggle"
    ADD = "add"
    ERASE = "erase"
    SELECT = "select"
    SPECIAL = "special"


@dataclass(slots=True)
class PaintGesture:
    document_id: int
    split_id: int
    block_id: int
    raw: bytes
    revision: int
    targets: set[CellTarget] = field(default_factory=set)


@dataclass(slots=True)
class EditorSession:
    """Transient user state, never part of the NX20 document."""

    document_id: int
    active_blocks: dict[int, int]
    profile: InteractionProfile = InteractionProfile.STUDIO
    tool: InteractionTool = InteractionTool.TOGGLE
    hover: CellTarget | None = None
    keyboard_target: CellTarget | None = None
    selection: CellSelection = field(default_factory=CellSelection)
    scroll_y: float = 0.0
    zoom: float = 1.0
    gesture: PaintGesture | None = None


def _row_in_block(rows, row_id: int):
    """Index compact rows without iterating through a complete chart."""
    if isinstance(rows, (CompactRows, OverlayRows)):
        base = rows.base if isinstance(rows, OverlayRows) else rows
        index = bisect_left(base._row_ids, row_id)
        if index < len(base) and int(base._row_ids[index]) == row_id:
            return rows[index]
        return None
    for row in rows:
        if row.stable_id == row_id:
            return row
    return None


class EditorController:
    """Single entry point for an opt-in editor's document mutations.

    The controller owns the session but not the low-level edit semantics:
    commands execute on the caller-supplied CommandStack. Existing GUI users
    can call sync_external_change() when they change that same stack.
    """

    def __init__(self, stack: CommandStack) -> None:
        self._stack = stack
        self._known_document = stack.current
        self._revision = 0
        self._snapshot = create_authoring_snapshot(stack.current)
        self.session = EditorSession(
            document_id=stack.current.stable_id,
            active_blocks=dict(self._snapshot.active_blocks),
        )

    @property
    def document(self):
        return self._stack.current

    @property
    def snapshot(self) -> AuthoringSnapshot:
        return self._snapshot

    def _check_synced(self) -> None:
        if self._stack.current is not self._known_document:
            self.cancel_stroke()
            raise EditorContextError(
                "document changed outside EditorController; call sync_external_change()"
            )

    def _reproject(self) -> None:
        old_choices = self.session.active_blocks
        snapshot = create_authoring_snapshot(self._stack.current)
        for split in snapshot.splits:
            old_block_id = old_choices.get(split.stable_id)
            if old_block_id is not None and any(
                block.stable_id == old_block_id for block in split.blocks
            ):
                snapshot = snapshot.with_active_block(split.stable_id, old_block_id)
        self._snapshot = snapshot
        self._known_document = self._stack.current
        self.session.document_id = self._stack.current.stable_id
        self.session.active_blocks = dict(snapshot.active_blocks)
        self._revision += 1

    def sync_external_change(self) -> None:
        """Reproject after a legacy frontend edits the shared command stack."""
        self.cancel_stroke()
        self._reproject()

    def select_block(self, split_id: int, block_id: int) -> None:
        self._check_synced()
        self.cancel_stroke()
        self._snapshot = self._snapshot.with_active_block(split_id, block_id)
        self.session.active_blocks = dict(self._snapshot.active_blocks)

    def cycle_block(self, split_id: int, delta: int = 1) -> None:
        self._check_synced()
        self.cancel_stroke()
        self._snapshot = self._snapshot.cycle_block(split_id, delta)
        self.session.active_blocks = dict(self._snapshot.active_blocks)

    def set_profile(self, profile: InteractionProfile) -> None:
        self.cancel_stroke()
        self.session.profile = InteractionProfile(profile)

    def set_tool(self, tool: InteractionTool) -> None:
        self.cancel_stroke()
        self.session.tool = InteractionTool(tool)

    def _validate_target(self, split_id: int, block_id: int, target: CellTarget) -> None:
        if self.session.document_id != self._stack.current.stable_id:
            raise EditorContextError("target belongs to a different document")
        try:
            selected = self._snapshot.active_block_id(split_id)
            block = self._snapshot.split(split_id).block(block_id)
        except KeyError as exc:
            raise EditorContextError("unknown Split or Block") from exc
        if selected != block_id:
            raise EditorContextError("target Block is not the selected alternative")
        if self._snapshot.effective_lightmap:
            raise EditorContextError("Lightmap uses a separate editing command path")
        if not 0 <= target.lane < self._snapshot.columns:
            raise EditorContextError("note lane is outside the chart")
        row = _row_in_block(block.rows, target.row_id)
        if row is None:
            raise EditorContextError("row does not belong to the selected Block")
        if isinstance(row, LightmapRow):
            raise EditorContextError("Lightmap rows cannot be edited as notes")

    def execute(self, command: Command):
        """Execute a preexisting domain command, not a GUI-local mutation."""
        self._check_synced()
        if self.session.gesture is not None:
            raise EditorContextError("finish or cancel the gesture before another edit")
        result = self._stack.execute(command)
        self._reproject()
        return result

    def set_note(self, split_id: int, block_id: int, target: CellTarget, raw: bytes):
        """Place exact NX20 note bytes; does not reinterpret existing holds."""
        self._check_synced()
        if self.session.gesture is not None:
            raise EditorContextError("cannot place a separate note during a gesture")
        self._validate_target(split_id, block_id, target)
        result = self._stack.execute(SetNoteAt(target.row_id, target.lane, raw))
        self._reproject()
        return result

    def start_stroke(
        self,
        split_id: int,
        block_id: int,
        first_target: CellTarget,
        raw: bytes,
    ) -> None:
        """Begin a pending Add/Erase stroke. Document stays untouched."""
        self._check_synced()
        if self.session.gesture is not None:
            raise EditorContextError("a gesture is already in progress")
        if len(raw) != 4:
            raise ValueError("NX20 note data must be exactly four bytes")
        self._validate_target(split_id, block_id, first_target)
        gesture = PaintGesture(
            document_id=self.session.document_id,
            split_id=split_id,
            block_id=block_id,
            raw=raw,
            revision=self._revision,
        )
        gesture.targets.add(first_target)
        self.session.gesture = gesture

    def extend_stroke(self, target: CellTarget) -> None:
        self._check_synced()
        gesture = self.session.gesture
        if gesture is None:
            raise EditorContextError("no active gesture")
        self._validate_target(gesture.split_id, gesture.block_id, target)
        gesture.targets.add(target)

    def finish_stroke(self):
        """Commit all unique cells in one atomic SetNotesAt undo step."""
        self._check_synced()
        gesture = self.session.gesture
        if gesture is None:
            raise EditorContextError("no active gesture")
        if gesture.document_id != self.session.document_id or gesture.revision != self._revision:
            self.cancel_stroke()
            raise EditorContextError("the gesture is stale")
        for target in gesture.targets:
            self._validate_target(gesture.split_id, gesture.block_id, target)
        command = SetNotesAt(
            tuple(
                NoteEdit(target.row_id, target.lane, gesture.raw)
                for target in sorted(gesture.targets)
            )
        )
        # Keep the gesture pending if command validation fails. Callers may
        # cancel explicitly; the original document remains unchanged.
        result = self._stack.execute(command)
        self.session.gesture = None
        self._reproject()
        return result

    def cancel_stroke(self) -> None:
        self.session.gesture = None

    def undo(self):
        self.cancel_stroke()
        self._check_synced()
        result = self._stack.undo()
        self._reproject()
        return result

    def redo(self):
        self.cancel_stroke()
        self._check_synced()
        result = self._stack.redo()
        self._reproject()
        return result
